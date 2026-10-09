"""Низкоуровневое исполнение ADB только после разрешения и проверки границ."""
from __future__ import annotations
import threading
import time
from .adb_bridge import ADBBridge


class PanicStop:
    def __init__(self):
        self._flag = threading.Event()

    def stop(self):
        self._flag.set()

    def reset(self, *, user_confirmed=False):
        if not user_confirmed:
            raise PermissionError('Сброс PANIC STOP требует разрешения владельца')
        self._flag.clear()

    def is_stopped(self) -> bool:
        return self._flag.is_set()


class FastInput:
    """Без sendevent и обхода античита. Для онлайн-игр ввод блокируется."""
    def __init__(self, bridge: ADBBridge, stop: PanicStop | None = None,
                 zones=(), offline_approved=False, max_actions_per_second=3):
        self.bridge = bridge
        self.stop = stop or PanicStop()
        self.zones = tuple(tuple(int(n) for n in box) for box in zones)
        self.offline_approved = offline_approved
        self.min_interval = 1.0 / max(1, min(max_actions_per_second, 3))
        self._last = 0.0

    def _check(self, x: int, y: int, *, online=False) -> bool:
        if self.stop.is_stopped() or online or not self.offline_approved:
            return False
        return bool(self.zones and any(a <= x < c and b <= y < d for a,b,c,d in self.zones))

    def tap(self, x: int, y: int, *, online=False, now=None) -> bool:
        now = time.monotonic() if now is None else now
        if not self._check(x, y, online=online) or now - self._last < self.min_interval:
            return False
        self.bridge.tap(x, y)
        self._last = now
        return True

    def swipe(self, start: tuple[int,int], end: tuple[int,int], ms: int, *, online=False, now=None) -> bool:
        now = time.monotonic() if now is None else now
        if not (self._check(*start, online=online) and self._check(*end, online=online)):
            return False
        if now - self._last < self.min_interval:
            return False
        self.bridge.swipe(*start, *end, ms)
        self._last = now
        return True
