"""Временной ряд: калиброванные показатели UI и осторожный прогноз на 0.5 с."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
import math
import re
import time

import cv2
import numpy as np

from ..models import Observation


@dataclass(frozen=True)
class GameStateVector:
    timestamp: float
    hp: float | None = None            # Доля 0..1; None означает «неизвестно»
    mp: float | None = None
    distance: float | None = None      # Относительная дистанция до врага (диагональ=1)
    cooldowns: dict[str, float] = field(default_factory=dict)
    threat: float | None = None        # Доля 0..1; нужна калибровка игрового UI
    enemy_mage: bool | None = None
    valid_signals: int = 0


@dataclass(frozen=True)
class Prediction:
    horizon: float
    hp: float | None
    mp: float | None
    distance: float | None
    threat: float | None
    events: tuple[str, ...]
    confidence: float
    cooldowns: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"horizon": self.horizon, "hp": self.hp, "mp": self.mp,
                "distance": self.distance, "threat": self.threat,
                "events": list(self.events), "confidence": self.confidence,
                "cooldowns": self.cooldowns}


class GameStateExtractor:
    """Калибруемый ROI-анализ; никаких предположений о неизвестной игре."""
    def __init__(self, hp_roi=None, mp_roi=None):
        # ROI задаётся в нормализованных координатах (x1,y1,x2,y2), 0..1.
        self.hp_roi = hp_roi
        self.mp_roi = mp_roi

    @staticmethod
    def _bar_fraction(bgr: np.ndarray, roi, color: str) -> float | None:
        if roi is None:
            return None
        h, w = bgr.shape[:2]
        x1, y1, x2, y2 = roi
        if not all(0 <= v <= 1 for v in roi) or x1 >= x2 or y1 >= y2:
            return None
        crop = bgr[round(y1*h):round(y2*h), round(x1*w):round(x2*w)]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # Настраиваемые цветовые сегменты; это не универсальный детектор HP.
        lo, hi = ((35, 65, 60), (90, 255, 255)) if color == "hp" else ((90, 65, 60), (135, 255, 255))
        mask = cv2.inRange(hsv, np.array(lo), np.array(hi)) > 0
        col = np.mean(mask, axis=0)
        active = np.flatnonzero(col > 0.35)
        if len(active) < 2:
            return None
        # Предполагаем горизонтальную полосу, заполнение от левого края.
        # Если маска не начинается близко к левому краю, считаем неизвестной.
        if active[0] > max(3, int(mask.shape[1] * .12)):
            return None
        return max(0.0, min(1.0, (active[-1] + 1) / mask.shape[1]))

    def extract(self, obs: Observation, timestamp: float | None = None) -> GameStateVector:
        timestamp = time.monotonic() if timestamp is None else timestamp
        img = cv2.imdecode(np.frombuffer(obs.image_jpeg, np.uint8), cv2.IMREAD_COLOR)
        hp = self._bar_fraction(img, self.hp_roi, "hp") if img is not None else None
        mp = self._bar_fraction(img, self.mp_roi, "mp") if img is not None else None
        # Приоритет чисел OCR, если они распознаны однозначно (HP 40/100).
        cds = {}
        for entry in obs.text:
            s = entry.text.lower().strip()
            m = re.search(r"(?:hp|health|здоровье|здоровья)\s*[:=]?\s*(\d+)\s*/\s*(\d+)", s)
            if m and int(m[2]) > 0:
                hp = min(1.0, int(m[1]) / int(m[2]))
            m = re.search(r"(?:mp|mana|мана|маны)\s*[:=]?\s*(\d+)\s*/\s*(\d+)", s)
            if m and int(m[2]) > 0:
                mp = min(1.0, int(m[1]) / int(m[2]))
            m = re.fullmatch(r"(?:cooldown|cd|откат)\s+(\w+)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*s?", s)
            if m:
                cds[m[1]] = max(0., min(300., float(m[2].replace(",", "."))))
        # Координаты врагов — только из моделей с подтверждённой меткой.
        enemies = [b for b in obs.candidate_boxes if b.confidence >= .6 and
                   (b.label.lower().startswith("enemy") or b.label.lower() in ("враг", "mage_enemy"))]
        distance = None
        if enemies:
            cx, cy = obs.width / 2, obs.height / 2
            diag = math.hypot(obs.width, obs.height) or 1
            distance = min(math.hypot(b.center[0] - cx, b.center[1] - cy) / diag for b in enemies)
        mage = any("mage" in b.label.lower() or "маг" in b.label.lower() for b in enemies) if enemies else None
        # Не выводим «опасность 100%» только из факта наличия врага.
        threat = None
        signals = sum(v is not None for v in (hp, mp, distance, threat))
        return GameStateVector(timestamp, hp, mp, distance, cds, threat, mage, signals)


class TemporalPredictor:
    def __init__(self, window: int = 10, horizon: float = 0.5):
        if window < 2 or horizon <= 0:
            raise ValueError("Некорректные параметры прогнозирования")
        self.history: deque[GameStateVector] = deque(maxlen=window)
        self.horizon = horizon

    def add(self, state: GameStateVector) -> None:
        if self.history and state.timestamp <= self.history[-1].timestamp:
            raise ValueError("Метки времени должны возрастать")
        self.history.append(state)

    def _forecast(self, name: str) -> tuple[float | None, float]:
        points = [(v.timestamp, getattr(v, name)) for v in self.history
                  if getattr(v, name) is not None]
        if not points:
            return None, 0.
        if len(points) == 1:
            return float(points[-1][1]), 0.
        t = np.array([x[0] - points[-1][0] for x in points], dtype=float)
        y = np.array([x[1] for x in points], dtype=float)
        if t[-1] - t[0] <= 0.05:
            return float(y[-1]), 0.
        slope = float(np.polyfit(t, y, deg=1)[0])
        # Ограничение разлёта исключает катастрофические прогнозы из OCR-шумов.
        slope = max(-1.0, min(1.0, slope))
        pred = max(0., min(1., float(y[-1]) + slope * self.horizon))
        residual = np.mean(np.abs(y - np.polyval(np.polyfit(t, y, deg=1), t)))
        conf = min(.9, len(points)/10) * max(.1, 1.0 - 4*float(residual))
        return pred, conf

    def predict(self) -> Prediction:
        hp, hc = self._forecast("hp")
        mp, mc = self._forecast("mp")
        distance, dc = self._forecast("distance")
        threat, tc = self._forecast("threat")
        strengths = [c for x,c in ((hp,hc),(mp,mc),(distance,dc),(threat,tc)) if x is not None]
        confidence = min(strengths) if strengths else 0.
        # События — подсказки. Они НЕ преобразуются напрямую в касания.
        events = []
        current = self.history[-1] if self.history else None
        if hp is not None and current and current.hp is not None and hp < .2 and hc >= .3:
            events.append("low_hp_soon")
        if distance is not None and current and current.distance is not None and dc >= .3:
            if distance < .15 and distance < current.distance:
                events.append("enemy_approaching")
        if threat is not None and threat > .8 and tc >= .3:
            events.append("possible_attack")
        cds = {name: max(0.0, secs - self.horizon)
               for name, secs in (current.cooldowns.items() if current else ())}
        return Prediction(self.horizon, hp, mp, distance, threat, tuple(events),
                          round(confidence, 3), cds)
