"""CircuitPython code.py (Raspberry Pi Pico): USB HID-клавиатура/мышь для собственного стенда.

СХЕМА (важно):
- USB Pico -> Android в режиме USB Host/OTG (Pico выступает HID устройством).
- UART Pico GP1(RX), GP0(TX), GND -> USB-UART адаптер ПК (3.3 В TTL).
- Питание Pico от USB телефона. НЕ соединять два 5V источника напрямую.
- Нужен CircuitPython и библиотека adafruit_hid на CIRCUITPY.
- Это не устройство для обхода античита. Android-игра может не поддерживать мышь.
"""
import board
import busio
import json
import time
import usb_hid
from adafruit_hid.mouse import Mouse
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode

uart = busio.UART(board.GP0, board.GP1, baudrate=115200, timeout=.2)
mouse = Mouse(usb_hid.devices)
keyboard = Keyboard(usb_hid.devices)
KEYS = {"ESC": Keycode.ESCAPE, "ENTER": Keycode.ENTER, "SPACE": Keycode.SPACE}
last_action = 0


def ack(seq, ok):
    uart.write((json.dumps({"seq": seq, "ok": ok}) + "\n").encode("ascii"))


while True:
    raw = uart.readline()
    if not raw or len(raw) > 256:
        continue
    seq = -1
    try:
        pkt = json.loads(raw)
        seq = pkt.get("seq", -1)
        if pkt.get("v") != 1 or not isinstance(seq, int):
            raise ValueError("bad packet")
        # Минимальная защита от слишком частых HID-команд.
        if time.monotonic() - last_action < .015:
            time.sleep(.015)
        op = pkt.get("op")
        if op == "move":
            dx, dy = pkt.get("dx"), pkt.get("dy")
            if type(dx) != int or type(dy) != int or not (-100 <= dx <= 100 and -100 <= dy <= 100):
                raise ValueError("bad move")
            mouse.move(x=dx, y=dy)
        elif op == "click":
            mouse.click(Mouse.LEFT_BUTTON)
        elif op == "button":
            state = pkt.get("state")
            if state == "down": mouse.press(Mouse.LEFT_BUTTON)
            elif state == "up": mouse.release(Mouse.LEFT_BUTTON)
            else: raise ValueError("bad button")
        elif op == "key":
            name = pkt.get("code")
            if name not in KEYS: raise ValueError("bad key")
            keyboard.send(KEYS[name])
        else:
            raise ValueError("bad op")
        last_action = time.monotonic()
        ack(seq, True)
    except Exception:
        # При ошибке всегда отпускаем кнопки.
        mouse.release_all()
        keyboard.release_all()
        ack(seq, False)
