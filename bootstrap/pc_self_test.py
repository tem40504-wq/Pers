"""Результаты проверки не подменяются выдуманными 'PASS' и миллисекундами."""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from .environment_detector import EnvironmentDetector
from .manifest import DependencyManifest
from .model_registry import PCModelRegistry


@dataclass
class Check:
    name: str
    status: str
    detail: str


class PCSelfTest:
    def __init__(self, root: str | Path, manifest: DependencyManifest):
        self.root = Path(root).resolve()
        self.manifest = manifest

    def _adb_devices(self) -> Check:
        if not shutil.which('adb'):
            return Check('Android', 'SKIP', 'ADB отсутствует')
        try:
            p = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=8)
            if p.returncode:
                return Check('Android', 'FAIL', 'ADB вернул ошибку')
            lines = p.stdout.splitlines()[1:]
            good = [s.split()[0] for s in lines if len(s.split()) >= 2 and s.split()[1] == 'device']
            unauthorized = [s.split()[0] for s in lines if 'unauthorized' in s]
            if good:
                return Check('Android', 'PASS', f'Авторизовано устройств: {len(good)}')
            if unauthorized:
                return Check('Android', 'WARN', 'Нужно разрешение USB-отладки на телефоне')
            return Check('Android', 'WARN', 'Телефон не подключён')
        except (OSError, subprocess.TimeoutExpired):
            return Check('Android', 'FAIL', 'Не удалось опросить ADB')

    def run(self) -> list[Check]:
        report = EnvironmentDetector(self.root).detect()
        checks = [Check('Python 3.11+', 'PASS' if sys.version_info >= (3, 11) else 'FAIL', report.python),
                  Check('Свободно 50 ГБ+', 'PASS' if report.disk_free_gb >= 50 else 'WARN', f'{report.disk_free_gb} ГБ'),
                  Check('RAM 16 ГБ+', 'PASS' if report.ram_gb is not None and report.ram_gb >= 16 else 'WARN', f'{report.ram_gb} ГБ'),
                  Check('NVIDIA GPU', 'PASS' if report.gpu_name else 'SKIP', report.gpu_name or 'Не обнаружена'),
                  Check('ADB', 'PASS' if report.tools['adb'] else 'SKIP', report.tools['adb'] or 'Не установлен'),
                  Check('scrcpy', 'PASS' if report.tools['scrcpy'] else 'SKIP', report.tools['scrcpy'] or 'Не установлен')]
        # CUDA-проверка выполняется без установки и без глобального импорта torch.
        py = self.root / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        if py.is_file():
            try:
                code = ('import json,torch;print(json.dumps({"cuda":torch.cuda.is_available(),'
                        '"name":torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))')
                p = subprocess.run([str(py), '-c', code], capture_output=True, text=True, timeout=25)
                if p.returncode == 0:
                    d = json.loads(p.stdout.strip())
                    checks.append(Check('PyTorch CUDA', 'PASS' if d['cuda'] else 'WARN', d['name'] or 'GPU недоступен'))
                else:
                    checks.append(Check('PyTorch CUDA', 'SKIP', 'Torch отсутствует в .venv или несовместим'))
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
                checks.append(Check('PyTorch CUDA', 'SKIP', 'Проверка не выполнена'))
        else:
            checks.append(Check('PyTorch CUDA', 'SKIP', 'Виртуальное окружение ещё не создано'))
        registry = PCModelRegistry(self.root)
        for model in (m for m in self.manifest.components if m.category == 'model'):
            state = registry.status(model)
            checks.append(Check(model.id, 'PASS' if state == 'verified' else 'SKIP', state))
        checks.append(self._adb_devices())
        return checks

    def print_report(self) -> list[Check]:
        checks = self.run()
        for x in checks:
            print(f'[{x.status:<4}] {x.name}: {x.detail}')
        return checks
