"""Проверка USB и 20 скриншотов; ввод только при явном --input."""
import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path
from pc_core.adb_bridge import ADBBridge, ADBError


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8', errors='replace')
    p = argparse.ArgumentParser()
    p.add_argument('--adb')
    p.add_argument('--serial')
    p.add_argument('--stress', action='store_true')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--input', action='store_true', help='Выполнить реальный tap и swipe')
    group.add_argument('--no-input', action='store_true', help='Совместимый флаг: ввод выключен по умолчанию')
    p.add_argument('--capture-mode', choices=['auto', 'pull'], default='auto')
    args = p.parse_args(argv)
    bundled = Path('tools/android/platform-tools/adb.exe')
    adb = args.adb or (str(bundled) if bundled.is_file() else shutil.which('adb'))
    report = {'version': '9.5', 'capture_mode': args.capture_mode, 'input_enabled': args.input,
              'success': 0, 'failed': 0, 'frames': [], 'status': 'FAIL'}
    bridge = None
    def out(ok, n, text): print(f'[{"OK" if ok else "FAIL"}] {n}/6 {text}', flush=True)
    try:
        if not adb or not (Path(adb).is_file() or shutil.which(adb)):
            out(False, 1, 'ADB не найден. Укажи --adb tools\\android\\platform-tools\\adb.exe')
            return 1
        out(True, 1, f'ADB найден: {adb}')
        bridge = ADBBridge(serial=args.serial, adb_path=adb, capture_mode=args.capture_mode)
        devices = bridge.list_devices()
        if dict(devices).get(bridge.serial) != 'device':
            raise ADBError('Телефон недоступен', bridge.serial, str(devices))
        report['serial'] = bridge.serial
        out(True, 2, f'Устройств: {sum(st=="device" for _, st in devices)}; выбран {bridge.serial}')
        model = bridge._run(bridge._device_args(['shell', 'getprop', 'ro.product.model'])).stdout.decode(errors='replace').strip()
        if not model: raise ADBError('Пустая модель', bridge.serial)
        report['model'] = model
        out(True, 3, f'Модель: {model}')
        if args.stress:
            print('После 10-го снимка можно отключить/подключить кабель. Пауза 5 секунд.', flush=True)
        times = []
        for i in range(1, 21):
            start = time.monotonic()
            frame = {'index': i}
            try:
                data = bridge.screenshot_png()
                if not bridge._valid_png(data): raise ADBError('Некорректный PNG', bridge.serial)
                frame.update(ok=True, bytes=len(data))
                report['success'] += 1
                # Маленький корректный PNG не считается обрывом передачи.
                print(f'[OK] снимок {i}/20: {len(data)} байт', flush=True)
            except ADBError as exc:
                frame.update(ok=False, error=str(exc))
                report['failed'] += 1
                print(f'[FAIL] снимок {i}/20:\n{exc}', flush=True)
            frame['seconds'] = time.monotonic()-start
            times.append(frame['seconds'])
            report['frames'].append(frame)
            if args.stress and i == 10:
                print('Переподключи кабель сейчас, если хочешь проверить reconnect.', flush=True)
                time.sleep(5)
            if i < 20: time.sleep(.5)
        report['timing'] = {'min': min(times), 'avg': statistics.mean(times), 'max': max(times)}
        out(report['failed']==0, 4, f'Успешных {report["success"]}, провалов {report["failed"]}; min/avg/max {min(times):.3f}/{statistics.mean(times):.3f}/{max(times):.3f} сек')
        inputs_ok = True
        if args.input:
            if report['failed']:
                inputs_ok = False
                out(False, 5, 'Ввод пропущен: скриншоты не прошли')
            else:
                print('Выполняются tap 100 200 и swipe 100 200 300 400 300.', flush=True)
                bridge.tap(100, 200)
                bridge.swipe(100, 200, 300, 400, 300)
                out(True, 5, 'ADB принял команды ввода')
        else: print('[SKIP] 5/6 Ввод выключен; для отдельной проверки используй --input')
        ok = report['success']==20 and report['failed']==0 and inputs_ok
        report['status'] = 'PASS' if ok else 'FAIL'
        out(ok, 6, 'Итог: ' + report['status'] + '; exit code ' + str(0 if ok else 1))
        return 0 if ok else 1
    except (ADBError, OSError, ValueError) as exc:
        report['error'] = str(exc)
        print('[FAIL]', exc)
        return 1
    except KeyboardInterrupt:
        report['status'] = 'INTERRUPTED'
        print('Остановлено оператором.')
        return 130
    finally:
        if bridge: bridge.close()
        try:
            Path('reports').mkdir(exist_ok=True)
            Path('reports/adb_verify_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Отчёт: reports/adb_verify_report.json')
        except OSError as exc: print('Не удалось сохранить отчёт:', exc)


if __name__ == '__main__':
    raise SystemExit(main())
