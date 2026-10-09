"""Иерархический мозг: Manager планирует; Worker быстро выбирает тактику."""
from __future__ import annotations
import json
import re
import time
from .models import Action, Box, Observation
from .vlm import VLM, VLMError

# Эти слова не являются безусловно безопасными; внешний SafetyGate проверяет экран.
SAFE_LABELS = re.compile(r"^(play|start|continue|next|attack|fight|resume|ok|далее|начать|продолжить|играть|атака|вперед|вперёд|бой)$", re.I)


class Manager:
    def __init__(self, period=10.0, user_goal="исследовать интерфейс безопасно"):
        self.period = period
        self.user_goal = user_goal
        self.goal = "observe"
        self.updated_at = float("-inf")

    def update(self, obs: Observation, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        if now - self.updated_at < self.period and not obs.game_over:
            return self.goal
        # Приоритет пользовательской цели перед эвристиками; Manager НЕ кликает.
        if obs.game_over:
            self.goal = "reflect"
        elif obs.state == "battle":
            self.goal = "combat"
        elif obs.state == "quest":
            self.goal = "quest"
        elif any(k in self.user_goal.lower() for k in ("фарм", "farm")):
            self.goal = "farm"
        elif any(k in self.user_goal.lower() for k in ("квест", "quest")):
            self.goal = "quest"
        else:
            self.goal = "explore"
        self.updated_at = now
        return self.goal


class Worker:
    def __init__(self, vlm: VLM | None = None, vlm_cooldown=12.0):
        self.vlm = vlm
        self.vlm_cooldown = vlm_cooldown
        self.last_vlm_at = float("-inf")

    def decide(self, obs: Observation, goal: str, lessons: list[str] | None = None,
               now: float | None = None) -> Action:
        now = time.monotonic() if now is None else now
        if obs.game_over:
            return Action(reason="Поражение: остановка и рефлексия")
        # Тактик работает с локальными OCR-кнопками без VLM.
        for item in obs.text:
            if item.confidence >= .80 and SAFE_LABELS.fullmatch(item.text.strip()):
                x, y = item.box.center
                # Доверенный bbox OCR используется для проверки точки ПОСЛЕ jitter.
                return Action(kind="tap", x=x, y=y, confidence=item.confidence,
                              risk="safe", reason=f"OCR: {item.text[:60]}",
                              target=item.box)
        # Если обученный YOLO видит игровую кнопку, можно использовать bbox.
        for box in obs.candidate_boxes:
            if box.confidence >= .86 and SAFE_LABELS.fullmatch(box.label):
                x, y = box.center
                return Action(kind="tap", x=x, y=y, confidence=box.confidence,
                              risk="safe", reason=f"YOLO: {box.label}", target=box)
        # Третья ступень: VLM вызывается только по неопределённости и с cooldown.
        if self.vlm is None or now - self.last_vlm_at < self.vlm_cooldown:
            return Action(reason="Нет однозначной безопасной кнопки")
        self.last_vlm_at = now
        prompt = ("Ты универсальный наблюдатель Android-игры. Твоя задача: "
                  f"{goal}. Экран: {obs.width}x{obs.height}. "
                  f"OCR и CV: {json.dumps(obs.compact(), ensure_ascii=False)[:8000]}. "
                  f"Выводы из прошлых ошибок: {json.dumps((lessons or [])[:5], ensure_ascii=False)}. "
                  "Выбери одно действие, но если назначение кнопки неясно, "
                  "есть покупка, удаление, продажа, реклама или платёж — верни wait. "
                  "Координаты указывай В ПИКСЕЛЯХ ОРИГИНАЛЬНОГО ЭКРАНА, не JPEG. "
                  'Формат: {"action":"wait|tap|swipe", "confidence":0.0, "risk":"safe|uncertain|prohibited", '
                  '"reason":"...", "x":0,"y":0,"x1":0,"y1":0,"x2":0,"y2":0,"duration_ms":400}. ' 
                  "Не утверждай, что неизвестная кнопка безопасна.")
        try:
            return Action.parse(self.vlm.ask_json(obs.image_jpeg, prompt))
        except (VLMError, ValueError):
            return Action(reason="VLM недоступна или вернула ошибочный JSON")


class Brain:
    def __init__(self, manager: Manager, worker: Worker):
        self.manager = manager
        self.worker = worker

    def decide(self, obs: Observation, lessons: list[str] | None = None,
               now: float | None = None) -> tuple[str, Action]:
        goal = self.manager.update(obs, now)
        return goal, self.worker.decide(obs, goal, lessons=lessons, now=now)
