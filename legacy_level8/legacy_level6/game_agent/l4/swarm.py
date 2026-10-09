"""Четыре логических агента, детерминированный жизненный цикл без фоновых утечек."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import json
import time
from typing import Any
from ..models import Action, Observation
from .temporal import GameStateVector, Prediction
from .dsl import DSLInterpreter, DSLParseError
from .local_vlm import DSL_SCHEMA


@dataclass(frozen=True)
class Message:
    source: str
    target: str
    kind: str
    payload: dict[str, Any]
    scene_id: str
    timestamp: float


class SwarmBus:
    """Локальная ограниченная asyncio-шина; сообщения привязаны к сцене."""
    def __init__(self, maxsize: int = 32):
        self.maxsize = maxsize
        self.queues: dict[str, asyncio.Queue[Message]] = {}

    def channel(self, name: str) -> asyncio.Queue[Message]:
        if name not in self.queues:
            self.queues[name] = asyncio.Queue(maxsize=self.maxsize)
        return self.queues[name]

    async def publish(self, source: str, target: str, kind: str, payload: dict,
                      scene_id: str, timestamp: float):
        q = self.channel(target)
        # Переполненная очередь не тормозит критичный цикл игры.
        if q.full():
            try: q.get_nowait()
            except asyncio.QueueEmpty: pass
        await q.put(Message(source, target, kind, payload, scene_id, timestamp))

    def drain(self, target: str, scene_id: str, now: float, ttl=2.0) -> list[Message]:
        q = self.channel(target)
        result = []
        while True:
            try: msg = q.get_nowait()
            except asyncio.QueueEmpty: break
            if msg.scene_id == scene_id and 0 <= now - msg.timestamp <= ttl:
                result.append(msg)
        return result


class Commander:
    def __init__(self, legacy_manager):
        self.legacy_manager = legacy_manager

    async def tick(self, obs: Observation, bus: SwarmBus, now: float) -> str:
        # Не дублируем алгоритм постановки задач: вызываем старый Manager.
        goal = self.legacy_manager.update(obs, now)
        await bus.publish("commander", "tactician", "goal", {"goal": goal}, obs.scene_id, now)
        return goal


class Scout:
    async def tick(self, obs: Observation, state: GameStateVector,
                   prediction: Prediction, bus: SwarmBus, now: float):
        # Миникарта без настроенной модели не считается распознанной.
        enemy_boxes = [b for b in obs.candidate_boxes if "enemy" in b.label.lower() and b.confidence >= .75]
        if "enemy_approaching" in prediction.events or enemy_boxes and state.distance is not None and state.distance < .12:
            await bus.publish("scout", "tactician", "danger",
                              {"reason": "enemy_nearby"}, obs.scene_id, now)


class Logistic:
    async def tick(self, obs: Observation, state: GameStateVector,
                   prediction: Prediction, bus: SwarmBus, now: float):
        if (state.hp is not None and state.hp < .2) or "low_hp_soon" in prediction.events:
            await bus.publish("logistic", "tactician", "low_hp", {"hp": state.hp}, obs.scene_id, now)


class Tactician:
    def __init__(self, old_worker, dsl: DSLInterpreter, vlm=None,
                 vlm_cooldown=12.0, rules: list[str] | None = None):
        self.old_worker, self.dsl, self.vlm = old_worker, dsl, vlm
        self.vlm_cooldown = vlm_cooldown
        self.last_vlm_at = float("-inf")
        self.rules = rules or ["IF hp < 20% THEN use_potion('heal')"]

    @staticmethod
    def facts(obs, state, prediction):
        return {"hp": state.hp, "mp": state.mp, "distance": state.distance,
                "enemy_mage": state.enemy_mage, "threat": state.threat,
                "predicted_hp": prediction.hp, "predicted_mp": prediction.mp,
                "predicted_distance": prediction.distance,
                "predicted_threat": prediction.threat,
                "danger": bool(prediction.events), "game_over": obs.game_over}

    async def tick(self, obs: Observation, state: GameStateVector, prediction: Prediction,
                   goal: str, bus: SwarmBus, now: float, lessons=None) -> Action:
        incoming = bus.drain("tactician", obs.scene_id, now)
        if obs.game_over:
            return Action(reason="Game Over: все агенты остановлены")
        facts = self.facts(obs, state, prediction)
        for source in self.rules:
            try:
                action = self.dsl.interpret(source, facts, obs)
            except DSLParseError:
                continue
            if action.kind != "wait":
                return action
        urgent = [m for m in incoming if m.kind in ("low_hp", "danger")]
        # Нельзя использовать несуществующее зелье и нельзя придумывать координаты.
        if urgent:
            return Action(reason="Опасность: нет разрешённого действия из Skill Library")
        # Семантическое решение — только для неопределённой сцены.
        if self.vlm and obs.confidence < .7 and now - self.last_vlm_at >= self.vlm_cooldown:
            self.last_vlm_at = now
            prompt = ("Верни JSON: {\"dsl\":\"IF <условие> THEN <навык>('аргумент')\","
                      "\"confidence\":0.0}. Не используй x/y, Python или неизвестные имена. "
                      "Только разрешённые навыки, иначе IF False THEN wait(). "
                      f"Цель: {goal}. Данные: {json.dumps(facts, ensure_ascii=False)}. "
                      f"Сцена: {json.dumps(obs.compact(), ensure_ascii=False)[:3000]}.")
            try:
                answer = await asyncio.to_thread(self.vlm.ask_json, obs.image_jpeg, prompt, DSL_SCHEMA)
                if float(answer.get("confidence", 0)) >= .7:
                    action = self.dsl.interpret(answer["dsl"], facts, obs)
                    if action.kind != "wait":
                        return action
            except (ValueError, KeyError, TypeError, DSLParseError, OSError):
                pass
        # Полная обратная совместимость: старый Worker как последний fallback.
        return self.old_worker.decide(obs, goal, lessons=lessons, now=now)


class SwarmCoordinator:
    def __init__(self, manager, worker, dsl: DSLInterpreter, vlm=None,
                 rules=None, vlm_cooldown=12.0):
        self.bus = SwarmBus()
        self.commander = Commander(manager)
        self.scout = Scout()
        self.logistic = Logistic()
        self.tactician = Tactician(worker, dsl, vlm, vlm_cooldown, rules)

    async def decide(self, obs: Observation, state: GameStateVector,
                     prediction: Prediction, now: float, lessons=None):
        goal_task = self.commander.tick(obs, self.bus, now)
        await asyncio.gather(
            self.scout.tick(obs, state, prediction, self.bus, now),
            self.logistic.tick(obs, state, prediction, self.bus, now))
        goal = await goal_task
        action = await self.tactician.tick(obs, state, prediction, goal, self.bus, now, lessons)
        return goal, action
