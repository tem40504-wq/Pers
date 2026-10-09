"""PC-as-Brain; безопасный режим без ввода по умолчанию."""
from __future__ import annotations
import argparse
from pathlib import Path
from bootstrap.environment_detector import EnvironmentDetector
from bootstrap.pc_self_test import PCSelfTest
from bootstrap.manifest import DependencyManifest
from pc_core.adb_bridge import DeviceManager, ADBBridge, ADBError
from pc_core.fast_input import FastInput, PanicStop
from pc_core.dashboard import ControlDashboard
from pc_core.legacy_device import GuardedLegacyDevice
from pc_core.pc_agent_adapter import legacy_agent


def main(argv=None):
    p = argparse.ArgumentParser(description='Universal Game Agent L9 — PC-as-Brain')
    p.add_argument('--preflight', action='store_true', help='Только диагностика ПК и подключённого телефона')
    p.add_argument('--device', help='ADB serial; обязателен при нескольких устройствах')
    p.add_argument('--dashboard', action='store_true', help='Локальная панель с PANIC STOP')
    p.add_argument('--game', default='generic')
    p.add_argument('--steps', type=int, default=5)
    p.add_argument('--offline-approved', action='store_true', help='Оператор подтвердил офлайн-стенд')
    p.add_argument('--execute', action='store_true', help='Разрешить действия после отдельного Y/N')
    p.add_argument('--safe-zone', action='append', default=[], help='x1,y1,x2,y2')
    args = p.parse_args(argv)
    root = Path(__file__).resolve().parent
    if args.steps < 0:
        p.error('steps должно быть >=0')
    if args.preflight:
        checks = PCSelfTest(root, DependencyManifest(root/'bootstrap'/'dependencies_pc.yaml')).print_report()
        # Запускатор не начинает работу без телефона и подходящего Python.
        critical = [c for c in checks if (c.name == 'Python 3.11+' and c.status != 'PASS')
                    or (c.name == 'Android' and c.status != 'PASS')]
        if critical:
            raise SystemExit(2)
        return
    zones = []
    for s in args.safe_zone:
        try:
            r = tuple(map(int, s.split(',')))
        except ValueError:
            p.error('safe-zone: x1,y1,x2,y2')
        if len(r) != 4 or min(r) < 0 or r[0] >= r[2] or r[1] >= r[3]:
            p.error('Некорректная --safe-zone')
        zones.append(r)
    if args.execute:
        if not args.offline_approved or not zones:
            p.error('--execute требует --offline-approved и хотя бы одну --safe-zone')
        try:
            allow = input('ВНИМАНИЕ: касания будут выполнены в разрешённой ОФЛАЙН-игре. Y/N: ')
        except (OSError, EOFError, KeyboardInterrupt):
            allow = 'N'
        if allow.strip().upper() != 'Y':
            print('Отказ — запускайте без --execute для проверки без касаний')
            return
    device = DeviceManager().selected(args.device)
    Agent, Settings = legacy_agent(root)
    cfg = Settings(serial=device.serial, game_id=args.game,
                   dry_run=not args.execute, safe_zones=tuple(zones),
                   enable_yolo=False, enable_ocr=False, enable_chroma=False,
                   max_steps=args.steps, memory_dir=str(root/'runtime'/'pc_l9'))
    print('Устройство:', device.serial, '|', 'REAL OFFLINE' if args.execute else 'DRY RUN')
    bridge = ADBBridge(device.serial)
    emergency = PanicStop()
    guard = FastInput(bridge, stop=emergency, zones=zones, offline_approved=args.execute and args.offline_approved)
    # Дополнительный Safety Gate находится ПЕРЕД ADBBridge, старый ActionExecutor сохранён.
    guarded_device = GuardedLegacyDevice(bridge, guard)
    dashboard = ControlDashboard(emergency) if args.dashboard else None
    if dashboard:
        import webbrowser
        url = dashboard.start()
        print('Локальная панель:', url)
        webbrowser.open(url)
    agent = Agent(cfg, device=guarded_device)
    if dashboard:
        old_step = agent.step
        def step_with_status():
            result = old_step()
            dashboard.update(result)
            return result
        agent.step = step_with_status
    try:
        agent.run()
    finally:
        if dashboard:
            dashboard.close()


if __name__ == '__main__':
    try:
        main()
    except (ADBError, RuntimeError, ImportError) as exc:
        print('Проверка запуска остановлена:', exc)
        print('Выполните сначала: python -m bootstrap.bootstrap --self-test')
        raise SystemExit(1)
