"""ADB-мост для собственного USB-устройства; без низкоуровневых инъекций."""
from __future__ import annotations
import re
import shutil
import subprocess
from dataclasses import dataclass


class ADBError(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    serial: str
    state: str


class DeviceManager:
    def __init__(self, adb_path: str = 'adb', runner=subprocess.run):
        self.adb_path, self.runner = adb_path, runner

    def devices(self) -> list[Device]:
        p = self.runner([self.adb_path, 'devices'], capture_output=True,
                        timeout=8, check=False)
        if p.returncode:
            raise ADBError('ADB devices завершился с ошибкой')
        devices = []
        for line in p.stdout.decode(errors='replace').splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] in {'device', 'unauthorized', 'offline'}:
                devices.append(Device(parts[0], parts[1]))
        return devices

    def selected(self, serial: str | None = None) -> Device:
        enabled = [d for d in self.devices() if d.state == 'device']
        if serial:
            matches = [d for d in enabled if d.serial == serial]
            if not matches:
                raise ADBError('Указанное устройство не подключено и не авторизовано')
            return matches[0]
        if len(enabled) != 1:
            raise ADBError(f'Требуется ровно одно устройство или явный --device: обнаружено {len(enabled)}')
        return enabled[0]


class ADBBridge:
    def __init__(self, serial: str, adb_path: str = 'adb', runner=subprocess.run):
        if not serial or '\x00' in serial or len(serial) > 256:
            raise ValueError('Недопустимый идентификатор телефона')
        self.serial, self.adb_path, self.runner = serial, adb_path, runner

    def _run(self, args: list[str], timeout: int = 12) -> bytes:
        # Только фиксированные аргументы и без shell=True.
        p = self.runner([self.adb_path, '-s', self.serial, *args],
                        capture_output=True, timeout=timeout, check=False)
        if p.returncode:
            raise ADBError((p.stderr or b'ADB command failed').decode(errors='replace')[:300])
        return p.stdout

    def screenshot_png(self) -> bytes:
        data = self._run(['exec-out', 'screencap', '-p'], timeout=20)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ADBError('Не получен корректный PNG от телефона')
        return data

    def tap(self, x: int, y: int):
        if type(x) is not int or type(y) is not int or x < 0 or y < 0:
            raise ValueError('Недопустимые координаты')
        self._run(['shell', 'input', 'tap', str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int):
        if any(type(v) is not int or v < 0 for v in (x1,y1,x2,y2)):
            raise ValueError('Недопустимые координаты')
        if not 100 <= duration_ms <= 2000:
            raise ValueError('Недопустимая продолжительность жеста')
        self._run(['shell', 'input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration_ms)])


class ADBDiagnostics:
    """Вызывается по явному запросу оператора; не взаимодействует с игрой."""
    def __init__(self, bridge: ADBBridge):
        self.bridge = bridge

    def properties(self) -> dict:
        model = self.bridge._run(['shell', 'getprop', 'ro.product.model']).decode(errors='replace').strip()
        release = self.bridge._run(['shell', 'getprop', 'ro.build.version.release']).decode(errors='replace').strip()
        return {'model': model[:100], 'android': release[:20]}
