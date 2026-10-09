"""Командная точка входа; по умолчанию ТОЛЬКО диагностика."""
from __future__ import annotations
import argparse
from pathlib import Path
from .environment_detector import EnvironmentDetector
from .orchestrator import BootstrapOrchestrator
from .offline_bootstrap import OfflineBootstrap
from .permissions import PermissionDenied
from .pc_self_test import PCSelfTest
from .installers import installer_for_system


def main(argv=None):
    ap = argparse.ArgumentParser(description='PC-as-Brain Level 9: безопасная установка')
    ap.add_argument('--report', action='store_true', help='Диагностика, ничего не меняет')
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--apply', nargs='+', metavar='ID', help='Установить только одобренные компоненты с SHA-256')
    ap.add_argument('--profile', choices=['windows-base','windows-tests','windows-screen'], help='Установить закреплённый полный профиль')
    ap.add_argument('--create-venv', action='store_true')
    ap.add_argument('--download-only', nargs='+', metavar='ID')
    ap.add_argument('--offline-dir', help='Каталог локальных проверенных архивов')
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    orchestrator = BootstrapOrchestrator(root)
    if args.apply and args.profile:
        ap.error('--apply и --profile нельзя использовать одновременно')
    if args.apply or args.profile:
        ids = args.apply or orchestrator.manifest.profiles[args.profile]
        result = orchestrator.apply(ids,
                                    offline_dir=Path(args.offline_dir) if args.offline_dir else None,
                                    include_venv=args.create_venv)
        print('Одобренные установки выполнены:', result)
        if len(result) != len(ids):
            raise SystemExit(1)
    elif args.download_only:
        result = OfflineBootstrap(orchestrator.manifest, orchestrator.gate).download_bundle(
            args.download_only, root / 'offline_bundle')
        print('Проверенных файлов скачано:', len(result))
    elif args.create_venv:
        orchestrator.apply([], include_venv=True)
    elif args.self_test:
        PCSelfTest(root, orchestrator.manifest).print_report()
    else:
        orchestrator.preview()
        print('\nСистемные компоненты для ручной установки:')
        for line in installer_for_system().guidance():
            print(' -', line)
        print('Без --apply / --create-venv / --download-only никакие изменения НЕ производятся.')


if __name__ == '__main__':
    try:
        main()
    except (PermissionDenied, ValueError, FileNotFoundError) as exc:
        print('ОСТАНОВЛЕНО:', exc)
        raise SystemExit(2)
