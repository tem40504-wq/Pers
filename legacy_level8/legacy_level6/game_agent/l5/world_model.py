"""Осторожная обучаемая модель переходов + планирование 5–10 шагов.

Это НЕ DreamerV3: до накопления проверенных переходов предсказания не
используются для изменения реальных действий.
"""
from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Sequence
import math
import statistics

from ..l4.temporal import GameStateVector
from ..models import Action

FIELDS = ("hp", "mp", "distance", "threat")


def action_key(action: Action) -> str:
    # Ключ связан с доверенной меткой навыка/кнопки, а не только с координатой.
    label = action.target.label if action.target else "unlabeled"
    return f"{action.kind}:{label}"


@dataclass(frozen=True)
class ModelEstimate:
    next_state: GameStateVector
    confidence: float
    samples: int


@dataclass(frozen=True)
class Plan:
    action: Action
    score: float
    confidence: float
    used_model: bool
    rollout_steps: int
    explanation: str


class WorldModel:
    def __init__(self, horizon_s=0.5, max_samples=200, min_samples=5):
        self.dt = float(horizon_s)
        self.min_samples = int(min_samples)
        self.transitions = defaultdict(lambda: deque(maxlen=max_samples))

    def learn(self, before: GameStateVector, action: Action,
              after: GameStateVector) -> None:
        """Учимся только на реально выполненном и проверенном действии."""
        if action.kind == "wait" or after.timestamp <= before.timestamp:
            return
        if not any(getattr(before, k) is not None and getattr(after, k) is not None
                   for k in FIELDS):
            return
        duration = after.timestamp - before.timestamp
        if not (0.06 <= duration <= 10):
            return
        delta = {}
        for key in FIELDS:
            a, b = getattr(before, key), getattr(after, key)
            if a is not None and b is not None and all(math.isfinite(z) for z in (a,b)):
                # Изменение нормируем на секунду, а затем масштабируем на 0.5 с.
                delta[key] = max(-2., min(2., (b-a)/duration))
        if delta:
            self.transitions[action_key(action)].append(delta)

    def predict_next(self, state: GameStateVector, action: Action) -> ModelEstimate:
        if action.kind == "wait":
            return ModelEstimate(self._advance(state, {}), .75, 0)
        samples = self.transitions.get(action_key(action), ())
        if len(samples) < self.min_samples:
            return ModelEstimate(self._advance(state, {}), 0., len(samples))
        effects = {}
        variability = []
        for k in FIELDS:
            values = [d[k] for d in samples if k in d]
            if len(values) >= self.min_samples:
                effects[k] = statistics.median(values)
                variability.append(statistics.pstdev(values) if len(values)>1 else 0)
        if not effects:
            return ModelEstimate(self._advance(state, {}), 0., len(samples))
        # Confidence — эвристика согласованности, не калиброванная вероятность.
        confidence = min(.9, len(samples)/20) * max(.1, 1 - 2*statistics.mean(variability))
        return ModelEstimate(self._advance(state, effects), round(confidence, 3), len(samples))

    def _advance(self, state: GameStateVector, effects: dict) -> GameStateVector:
        def next_value(k):
            cur = getattr(state, k)
            return None if cur is None else max(0., min(1., cur + self.dt * effects.get(k, 0)))
        return GameStateVector(timestamp=state.timestamp + self.dt,
            hp=next_value("hp"), mp=next_value("mp"), distance=next_value("distance"),
            threat=next_value("threat"),
            cooldowns={k:max(0., v-self.dt) for k,v in state.cooldowns.items()},
            enemy_mage=state.enemy_mage, valid_signals=state.valid_signals)

    @staticmethod
    def _utility(state: GameStateVector) -> float:
        # Награда для безопасного PvE: выживание и снижение угрозы.
        return (2.0 * (state.hp if state.hp is not None else .5)
                - (state.threat if state.threat is not None else .25)
                + .15 * (state.mp if state.mp is not None else .5))

    def planning(self, state: GameStateVector, candidates: Sequence[Action],
                 steps: int = 6, fallback: Action | None = None,
                 beam_width: int = 6) -> Plan:
        """Beam-search rollout: 5–10 виртуальных действий, выполняется только первое.

        Выбирает исключительно уже разрешённые и подтверждённые навыки.
        При неизвестной модели любого кандидата сохраняется решение уровня 4.
        """
        if not 5 <= steps <= 10:
            raise ValueError("rollout: только 5–10 шагов")
        fallback = fallback or (candidates[0] if candidates else Action())
        eligible = [c for c in candidates if c.kind != "wait" and c.risk == "safe" and
                    c.confidence >= .7 and c.target is not None]
        if not eligible or state.hp is None:
            return Plan(fallback, 0., 0., False, steps, "Недостаточно калиброванных данных")
        # Кортеж: (состояние, первое действие, последнее действие, оценка, надёжность)
        beams = [(state, None, None, 0., 1.)]
        for t in range(steps):
            expanded = []
            for current, first, previous, score, conf in beams:
                for action in eligible:
                    estimate = self.predict_next(current, action)
                    if estimate.confidence < .65:
                        continue
                    new_conf = min(conf, estimate.confidence)
                    # Лёгкий штраф за повторение, чтобы не поощрять зацикливание.
                    repetition_penalty = .10 if previous == action else 0.
                    new_score = score + (.90 ** t) * self._utility(estimate.next_state) - repetition_penalty
                    expanded.append((estimate.next_state, first or action, action, new_score, new_conf))
            if not expanded:
                return Plan(fallback,0.,0.,False,steps,
                            "Нехватка проверенных переходов, используется L4")
            expanded.sort(key=lambda row: row[3],reverse=True)
            beams = expanded[:max(1,beam_width)]
        best = max(beams,key=lambda row: row[3])
        return Plan(best[1],best[3],best[4],True,steps,
                    "Beam-search оценил последовательности только подтверждённых навыков")
