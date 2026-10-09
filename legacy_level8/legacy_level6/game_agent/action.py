"""Ограничитель опасных касаний и вариативные жесты (не средство обхода правил)."""
from __future__ import annotations
import math
import random
import re
import time
from typing import Protocol
from .models import Action, Box, Observation

RISKY = re.compile(
    r"(buy|purchase|sell|delete|discard|shop|checkout|pay|confirm purchase|"
    r"купить|покупк|продать|удалить|уничтож|магазин|оплат|донат|плат[её]ж|"
    r"удаление|продажа|потратить|списать)", re.I)


class GestureBackend(Protocol):
    def drag_path(self, points: list[tuple[int, int]], duration_ms: int) -> None: ...


def bezier_points(start: tuple[int, int], end: tuple[int, int], count=16,
                  rng: random.Random | None = None) -> list[tuple[int, int]]:
    """Генерирует точки кубической кривой Безье без отправки на телефон."""
    rng = rng or random.Random()
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length = math.hypot(dx, dy)
    lateral = min(24, length * .12)
    if length == 0:
        return [start] * count
    nx, ny = -dy / length, dx / length
    p1 = (sx + dx * .33 + nx * rng.uniform(-lateral, lateral),
          sy + dy * .33 + ny * rng.uniform(-lateral, lateral))
    p2 = (sx + dx * .66 + nx * rng.uniform(-lateral, lateral),
          sy + dy * .66 + ny * rng.uniform(-lateral, lateral))
    out = []
    for i in range(count):
        t = i / (count - 1)
        u = 1 - t
        x = u**3*sx + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*ex
        y = u**3*sy + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*ey
        out.append((round(x), round(y)))
    return out


class ActionExecutor:
    def __init__(self, device, safe_zones: tuple[tuple[int,int,int,int], ...] = (),
                 threshold=.72, backend: GestureBackend | None = None,
                 rng: random.Random | None = None, sleep=time.sleep):
        self.device = device
        self.safe_zones = tuple(Box(*z) for z in safe_zones)
        self.threshold = threshold
        self.backend = backend
        self.rng = rng or random.Random()
        self.sleep = sleep

    def _point_ok(self, x: int, y: int, obs: Observation, target: Box | None) -> bool:
        if not (type(x) is int and type(y) is int and 0 <= x < obs.width and 0 <= y < obs.height):
            return False
        # Только известная локальная кнопка ИЛИ заранее согласованная зона.
        if not (target and target.contains(x, y) or any(b.contains(x, y) for b in self.safe_zones)):
            return False
        # Координата НЕ может попадать в текстовые области риска.
        if any(RISKY.search(item.text) and item.box.contains(x, y, margin=-8) for item in obs.text):
            return False
        return True

    def _safe(self, action: Action, obs: Observation) -> bool:
        if action.risk != "safe" or action.confidence < self.threshold:
            return False
        if RISKY.search(action.reason):
            return False
        # Даже если OCR нашёл риск на другом участке экрана — блокируем весь ввод.
        # Это заведомо консервативно; для реальной игры понадобится настройка.
        if any(RISKY.search(t.text) for t in obs.text):
            return False
        return True

    def human_tap(self, x: int, y: int, obs: Observation, target: Box | None,
                  dry_run=True) -> tuple[str, tuple[int, int]]:
        # Радиус до 15 px, но никогда не выходить за проверенную область.
        dx = self.rng.randint(-15, 15)
        dy = self.rng.randint(-15, 15)
        px, py = x + dx, y + dy
        if not self._point_ok(px, py, obs, target):
            # Сдвиг может попасть за границу: безопасно используем центр.
            px, py = x, y
        if not self._point_ok(px, py, obs, target):
            return "blocked:point", (px, py)
        if not dry_run:
            self.device.tap(px, py)
            self.sleep(self.rng.uniform(.1, .5))
        return ("dry_run" if dry_run else "executed"), (px, py)

    def human_swipe(self, action: Action, obs: Observation, dry_run=True) -> tuple[str, list]:
        start = (action.x1, action.y1)
        end = (action.x2, action.y2)
        if not all(self._point_ok(*p, obs, action.target) for p in (start, end)):
            return "blocked:point", []
        path = bezier_points(start, end, rng=self.rng)
        # Проверяем всю рассчитанную траекторию, не только конечные точки.
        if not all(self._point_ok(*p, obs, action.target) for p in path):
            return "blocked:path", path
        duration = max(100, min(2000, int(action.duration_ms * self.rng.uniform(.85, 1.15))))
        if not dry_run:
            if self.backend is not None:
                self.backend.drag_path(path, duration)
                status = "executed:bezier"
            else:
                # Стандартный ADB input swipe линейный. Непрерывное Безье требует
                # специального gesture backend (например, AccessibilityService).
                self.device.swipe(*start, *end, duration)
                status = "executed:linear_fallback"
            self.sleep(self.rng.uniform(.1, .5))
        else:
            status = "dry_run"
        return status, path

    def execute(self, action: Action, obs: Observation, dry_run=True) -> dict:
        if action.kind == "wait":
            return {"status": "wait", "action": action.as_dict()}
        if not self._safe(action, obs):
            return {"status": "blocked:risk", "action": action.as_dict()}
        if action.kind == "tap":
            status, point = self.human_tap(action.x, action.y, obs, action.target, dry_run)
            return {"status": status, "point": point, "action": action.as_dict()}
        if action.kind == "swipe":
            status, path = self.human_swipe(action, obs, dry_run)
            return {"status": status, "path": path, "action": action.as_dict()}
        return {"status": "blocked:unknown_action"}
