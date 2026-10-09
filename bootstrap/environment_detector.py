"""Диагностика ПК без установок, сетевых вызовов и изменения настроек."""
from __future__ import annotations
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


def _ram_bytes() -> int | None:
    if sys.platform == 'linux':
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                if line.startswith('MemTotal:'):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == 'win32':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        try:
            value = MemoryStatus()
            value.dwLength = ctypes.sizeof(value)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
                return value.ullTotalPhys
        except (AttributeError, OSError):
            return None
    return None


def _command_version(name: str) -> str | None:
    path = shutil.which(name)
    if not path:
        return None
    args = {'git': ['--version'], 'ffmpeg': ['-version'], 'adb': ['version'],
            'scrcpy': ['--version'], 'pip': ['--version']}
    try:
        out = subprocess.run([path, *args.get(name, ['--version'])],
                             capture_output=True, text=True, errors='replace', timeout=6)
        return (out.stdout or out.stderr).strip().splitlines()[0][:250] if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return None


@dataclass(frozen=True)
class EnvironmentReport:
    system: str
    release: str
    architecture: str
    python: str
    ram_gb: float | None
    disk_free_gb: float
    gpu_name: str | None
    gpu_driver: str | None
    gpu_vram_mb: int | None
    tools: dict[str, str | None]
    errors: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


class EnvironmentDetector:
    """Только читает локальное окружение, ничего не скачивает."""
    def __init__(self, root: str | Path = '.'):
        self.root = Path(root).resolve()

    def detect(self) -> EnvironmentReport:
        disk = shutil.disk_usage(self.root)
        ram = _ram_bytes()
        gpu_name = gpu_driver = None
        gpu_vram = None
        errors: list[str] = []
        if shutil.which('nvidia-smi'):
            try:
                p = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total',
                                    '--format=csv,noheader,nounits'], capture_output=True,
                                   text=True, timeout=8)
                if p.returncode == 0 and p.stdout.strip():
                    first = p.stdout.strip().splitlines()[0].split(',')
                    if len(first) >= 3:
                        gpu_name, gpu_driver = first[0].strip(), first[1].strip()
                        gpu_vram = int(first[2].strip().split()[0])
                else:
                    errors.append('nvidia-smi найден, но сведения о видеокарте не получены')
            except (OSError, subprocess.TimeoutExpired, ValueError):
                errors.append('Не удалось запросить nvidia-smi')
        tools = {tool: _command_version(tool) for tool in ('git', 'ffmpeg', 'adb', 'scrcpy', 'pip')}
        return EnvironmentReport(platform.system(), platform.release(), platform.machine(),
                                 platform.python_version(), round(ram/2**30, 1) if ram else None,
                                 round(disk.free/2**30, 1), gpu_name, gpu_driver, gpu_vram,
                                 tools, tuple(errors))

    def formatted(self) -> str:
        return json.dumps(self.detect().as_dict(), indent=2, ensure_ascii=False)
