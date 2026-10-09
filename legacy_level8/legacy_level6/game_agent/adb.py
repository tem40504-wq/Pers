"""Безопасный USB/ADB транспорт без выполнения строк модели в shell."""
import subprocess


class ADBError(RuntimeError):
    pass


class ADBDevice:
    def __init__(self, adb_path="adb", serial=None):
        self.adb_path = adb_path
        self.serial = serial
        if self.serial is None:
            raw = self._run(["devices"])
            lines = raw.decode("utf-8", "replace").splitlines()[1:]
            devices = [line.split()[0] for line in lines if len(line.split()) >= 2 and line.split()[1] == "device"]
            if len(devices) != 1:
                raise ADBError(f"Нужен один авторизованный телефон, обнаружено: {devices}")
            self.serial = devices[0]

    def _run(self, argv: list[str], timeout=20) -> bytes:
        cmd = [self.adb_path] + (["-s", self.serial] if self.serial else []) + argv
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ADBError(str(e)) from e
        if p.returncode:
            raise ADBError(p.stderr.decode("utf-8", "replace")[:500])
        return p.stdout

    def screenshot_png(self) -> bytes:
        png = self._run(["exec-out", "screencap", "-p"])
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ADBError("ADB не вернул PNG")
        return png

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self._run(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
