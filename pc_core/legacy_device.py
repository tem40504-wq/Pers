"""Адаптер к старому GameAgent: ADBBridge + дополнительный разрешающий фильтр."""
from .fast_input import FastInput
from .adb_bridge import ADBBridge


class GuardedLegacyDevice:
    def __init__(self, bridge: ADBBridge, input_guard: FastInput):
        self.bridge, self.input_guard = bridge, input_guard

    def screenshot_png(self) -> bytes:
        return self.bridge.screenshot_png()

    def tap(self, x: int, y: int):
        if not self.input_guard.tap(x, y):
            raise PermissionError('Ввод заблокирован PC Safety Gate')

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int):
        if not self.input_guard.swipe((x1, y1), (x2, y2), duration_ms):
            raise PermissionError('Свайп заблокирован PC Safety Gate')
