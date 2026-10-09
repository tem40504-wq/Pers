"""Изолированная установка только из хешированных локальных колёс."""
from __future__ import annotations
import os
import subprocess
import sys
import venv
from pathlib import Path
from .pc_downloader import sha256_file


class VenvManager:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.path = self.root / '.venv'

    def python(self) -> Path:
        if os.name == 'nt':
            return self.path / 'Scripts' / 'python.exe'
        return self.path / 'bin' / 'python'

    def create(self) -> Path:
        # Вызывается исключительно после PermissionGate.Y.
        venv.EnvBuilder(with_pip=True, clear=False).create(self.path)
        if not self.python().is_file():
            raise RuntimeError('Не удалось создать виртуальное окружение')
        return self.python()

    def install_wheel(self, wheel_path: str | Path, expected_sha256: str):
        wheel = Path(wheel_path).resolve()
        if wheel.suffix != '.whl' or not wheel.is_file():
            raise ValueError('Нужен локальный .whl')
        if sha256_file(wheel).lower() != expected_sha256.lower():
            raise ValueError('SHA-256 локального колеса не совпадает')
        if not self.python().is_file():
            raise RuntimeError('Виртуальное окружение отсутствует')
        # --no-deps исключает скрытую установку транзитивных зависимостей.
        return subprocess.run([str(self.python()), '-m', 'pip', 'install', '--no-index',
                               '--no-deps', '--disable-pip-version-check', '--no-input',
                               str(wheel)], check=True, timeout=600)
