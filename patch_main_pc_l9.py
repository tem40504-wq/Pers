"""Цикл с паузой ADB и точечное обновление main версии v9.4."""
import argparse
import datetime
import os
import tempfile
import time
from pathlib import Path
from pc_core.adb_bridge import ADBError, ADBWatchdog

MARKER = 'from patch_main_pc_l9 import run_with_adb_recovery'


def run_with_adb_recovery(agent, bridge, *, emergency=None, recovery_timeout=60):
    stop_event = getattr(emergency, '_flag', None)
    if not bridge.wait_for_device(timeout=30, stop_event=stop_event):
        if emergency and emergency.is_stopped(): return 0
        raise ADBError('Телефон не найден', bridge.serial, hint='Запусти VERIFY_ADB.bat.')
    watchdog = ADBWatchdog(bridge, interval=3)
    completed, pause_started = 0, None
    try:
        watchdog.start()
        while agent.cfg.max_steps == 0 or completed < agent.cfg.max_steps:
            if emergency and emergency.is_stopped():
                print('PANIC STOP активен. Сессия остановлена.')
                break
            if not watchdog.is_healthy():
                if pause_started is None:
                    pause_started = time.monotonic()
                    print('ADB проверяется или потерян. Пауза...')
                if time.monotonic()-pause_started >= recovery_timeout:
                    raise ADBError('Истёк таймаут паузы', bridge.serial, hint='Проверь USB; запусти VERIFY_ADB.bat.')
                if stop_event is None: time.sleep(.2)
                else: stop_event.wait(.2)
                continue
            pause_started = None
            started = time.monotonic()
            try:
                result = agent.step()
            except ADBError as exc:
                watchdog.paused.set()
                bridge.log.warning('Пауза агента: %s', exc)
                print(f'Ошибка ADB:\n{exc}')
                if not agent.cfg.dry_run:
                    if emergency: emergency.stop()
                    raise ADBError('Реальная сессия остановлена', bridge.serial, exc.stderr,
                                   'Проверь экран и подключение. Повторное действие автоматически не выполняется.',
                                   input_uncertain=True) from exc
                print(f'Ждём подключения до {recovery_timeout} секунд...')
                if not bridge.wait_for_device(timeout=recovery_timeout, stop_event=stop_event):
                    if emergency and emergency.is_stopped(): break
                    raise ADBError('Телефон не восстановился', bridge.serial, exc.stderr, exc.hint) from exc
                print('Телефон найден. Продолжаем наблюдение.')
                continue
            completed += 1
            bridge.log.info('Цикл %d: %s', completed, result)
            print(f'Цикл {completed}: {result.get("state", "unknown")} / {result.get("status", "unknown")}')
            delay = max(0, agent.cfg.worker_period-(time.monotonic()-started))
            if stop_event is None: time.sleep(delay)
            else: stop_event.wait(delay)
        return completed
    except KeyboardInterrupt:
        if emergency: emergency.stop()
        print('Остановлено оператором.')
        return completed
    finally:
        watchdog.stop()
        bridge.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--main', default='main_pc_l9.py')
    args = p.parse_args()
    target = Path(args.main)
    temp = None
    try:
        raw = target.read_bytes()
        text = raw.decode('utf-8-sig').replace('\r\n', '\n')
        if MARKER in text:
            print('Патч уже внедрён. Запускай VERIFY_ADB.bat.')
            return 0
        replacements = [
            ('from pc_core.adb_bridge import DeviceManager, ADBBridge, ADBError',
             'from pc_core.adb_bridge import DeviceManager, ADBBridge, ADBError\n' + MARKER),
            ('    device = DeviceManager().selected(args.device)',
             "    adb_path = str(root/'tools/android/platform-tools/adb.exe') if (root/'tools/android/platform-tools/adb.exe').is_file() else 'adb'\n    device = DeviceManager(adb_path=adb_path).selected(args.device)"),
            ('    bridge = ADBBridge(device.serial)',
             "    bridge = ADBBridge(serial=device.serial, adb_path=adb_path, log_dir=str(root/'logs'))"),
            ('        completed = agent.run()',
             '        completed = run_with_adb_recovery(agent, bridge, emergency=emergency)'),
            ('    except (ADBError, RuntimeError, ImportError, ValueError) as exc:',
             "    except ADBError as exc:\n        print('Сессия ADB остановлена:', exc)\n        print('Диагностика: VERIFY_ADB.bat')\n        raise SystemExit(1)\n    except (RuntimeError, ImportError, ValueError) as exc:"),
        ]
        for old, new in replacements:
            if text.count(old) != 1:
                raise ValueError('Main отличается от v9.4. Файл не изменён. Не найдена строка: ' + old)
            text = text.replace(old, new, 1)
        compile(text, str(target), 'exec')
        backup = target.with_name(target.stem + '.adb_backup_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.py')
        with backup.open('xb') as f: f.write(raw)
        newline = '\r\n' if b'\r\n' in raw else '\n'
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, delete=False) as f:
            temp = Path(f.name)
            f.write(text.replace('\n', newline).encode('utf-8'))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        temp = None
        print('Патч установлен. Копия:', backup)
        return 0
    except (OSError, ValueError, SyntaxError) as exc:
        print('Патч не установлен:', exc)
        return 1
    finally:
        if temp is not None: temp.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
