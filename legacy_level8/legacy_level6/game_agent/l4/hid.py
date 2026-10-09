"""Необязательное аппаратное HID-управление для тестовых стендов.
НЕ гарантирует обход защит игры. Скриншоты в любом случае остаются через ADB.
PC -- USB-UART -- Pico UART; Pico USB (HID) -- Android USB Host/OTG.
"""
from __future__ import annotations
import json
import threading
import time


class HIDError(RuntimeError):
    pass


class HIDUncalibrated(HIDError):
    """До отправки: можно безопасно использовать ADB."""


class HIDAckUncertain(HIDError):
    """Команда могла исполниться — повтор через ADB небезопасен."""


class SerialHIDTransport:
    """Ограниченный JSONL-протокол; никаких произвольных строк/скриптов."""
    def __init__(self, port: str, baudrate=115200, timeout=1.5, connection=None):
        self._serial = connection
        if self._serial is None:
            import serial  # pyserial, опционально
            self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        self._lock = threading.Lock()
        self._seq = 0
        self.timeout = timeout

    def send(self, op: str, **payload):
        if op not in ("move", "click", "key", "button"):
            raise HIDError("Недопустимая команда HID")
        if op == "move":
            if type(payload.get("dx")) is not int or type(payload.get("dy")) is not int:
                raise HIDError("Движение требует целые dx,dy")
            if not all(-100 <= payload[x] <= 100 for x in ("dx", "dy")):
                raise HIDError("Слишком большое смещение")
        elif op == "key" and payload.get("code") not in ("ESC", "ENTER", "SPACE"):
            raise HIDError("Клавиша не разрешена")
        elif op == "button" and payload.get("state") not in ("up", "down"):
            raise HIDError("Состояние кнопки должно быть up/down")
        elif op == "click" and payload:
            raise HIDError("У click нет аргументов")
        with self._lock:
            self._seq += 1
            data = {"v": 1, "seq": self._seq, "op": op, **payload}
            self._serial.write((json.dumps(data, separators=(",", ":")) + "\n").encode("ascii"))
            self._serial.flush()
            reply = self._serial.readline()
            try:
                ans = json.loads(reply)
            except Exception as exc:
                raise HIDAckUncertain("ACK неизвестен: команда могла выполниться") from exc
            if ans.get("seq") != self._seq or ans.get("ok") is not True:
                raise HIDAckUncertain("ACK отрицательный или не совпал номер: повтор запрещён")
            return ans

    def close(self):
        self._serial.close()


class CalibratedHIDInput:
    """Эмуляция мыши требует проверенной калибровки курсора на конкретном Android.
    Указание координат без калибровки запрещено.
    """
    def __init__(self, transport: SerialHIDTransport, x=None, y=None, calibrated=False):
        self.serial = transport
        self.x, self.y = x, y
        self.calibrated = calibrated

    def _move_to(self, x, y):
        if not self.calibrated or self.x is None or self.y is None:
            raise HIDUncalibrated("Мышь не откалибрована: включите ADB fallback")
        dx, dy = int(x - self.x), int(y - self.y)
        while dx or dy:
            stepx, stepy = max(-100, min(100, dx)), max(-100, min(100, dy))
            self.serial.send("move", dx=stepx, dy=stepy)
            dx -= stepx
            dy -= stepy
            self.x += stepx
            self.y += stepy

    def tap(self, x, y):
        self._move_to(x, y)
        self.serial.send("click")

    def swipe(self, x1, y1, x2, y2, duration_ms):
        self._move_to(x1, y1)
        self.serial.send("button", state="down")
        try:
            steps = max(2, int(duration_ms/70))
            for i in range(1, steps + 1):
                self._move_to(round(x1+(x2-x1)*i/steps), round(y1+(y2-y1)*i/steps))
                time.sleep(duration_ms/1000/steps)
        finally:
            self.serial.send("button", state="up")


class HIDWithADBFallback:
    def __init__(self, adb, hid=None):
        self.adb, self.hid = adb, hid

    def screenshot_png(self):
        return self.adb.screenshot_png()

    def tap(self, x, y):
        if self.hid:
            try:
                return self.hid.tap(x, y)
            except HIDUncalibrated:
                pass  # Курсор не калиброван: HID-команда ещё не отправлялась.
        return self.adb.tap(x, y)

    def swipe(self, x1, y1, x2, y2, duration_ms):
        if self.hid:
            try:
                return self.hid.swipe(x1, y1, x2, y2, duration_ms)
            except HIDUncalibrated:
                pass
        return self.adb.swipe(x1, y1, x2, y2, duration_ms)
