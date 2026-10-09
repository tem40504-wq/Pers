"""Windows entry point: keep batch parsing independent of Unicode output."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-launcher', action='store_true')
    parser.add_argument('--capture-mode', choices=['auto', 'pull'], default='auto')
    args = parser.parse_args(argv)
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    adb = ROOT / 'tools/android/platform-tools'
    env['PATH'] = str(adb) + os.pathsep + env.get('PATH', '')
    if args.check_launcher:
        code = "import sys,numpy,cv2,PIL,requests; print('LAUNCHER_CHECK: PASS'); print(sys.executable)"
        return subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, check=False).returncode
    preflight = subprocess.run([sys.executable, str(ROOT/'main_pc_l9.py'), '--preflight'], cwd=ROOT, env=env, check=False)
    if preflight.returncode:
        print('Проверьте подключение телефона и разрешение отладки по USB.')
        return preflight.returncode
    print('Тестовый запуск: 20 циклов наблюдения без нажатий.', flush=True)
    return subprocess.run([sys.executable, str(ROOT/'main_pc_l9.py'), '--steps', '20', '--dashboard', '--capture-mode', args.capture_mode], cwd=ROOT, env=env, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
