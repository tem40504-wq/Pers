"""Preflight -> одобренный список операций -> поэтапная проверка/установка."""
from __future__ import annotations
import importlib.util
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from .environment_detector import EnvironmentDetector
from .manifest import DependencyManifest, DependencySpec, artifact_filename
from .permissions import BatchPermissionGate, PermissionDenied
from .pc_downloader import PCDownloader, sha256_file
from .venv_manager import VenvManager
from .model_registry import PCModelRegistry


class BootstrapOrchestrator:
    def __init__(self, root: str | Path, gate: BatchPermissionGate | None = None):
        self.root = Path(root).resolve()
        self.manifest = DependencyManifest(self.root / 'bootstrap' / 'dependencies_pc.yaml')
        self.gate = gate or BatchPermissionGate(audit_path=self.root / 'logs' / 'bootstrap_audit.jsonl')
        self.downloader = PCDownloader()
        self.venv = VenvManager(self.root)
        self.registry = PCModelRegistry(self.root)
        self.journal = self.root / 'logs' / 'bootstrap_journal.jsonl'

    def status(self, spec: DependencySpec) -> str:
        if not spec.compatible():
            return 'incompatible'
        if spec.category == 'model':
            return self.registry.status(spec)
        if spec.import_name:
            try:
                return 'present' if importlib.util.find_spec(spec.import_name) else 'missing'
            except (ImportError, ValueError):
                return 'missing'
        if spec.executable:
            return 'present' if shutil.which(spec.executable) else 'missing'
        return 'manual_check'

    def missing(self) -> list[DependencySpec]:
        return [s for s in self.manifest.components if self.status(s) not in {'present', 'verified'}]

    def preview(self) -> list[dict]:
        d = EnvironmentDetector(self.root).detect()
        missing = self.missing()
        known = sum(s.size_mb or 0 for s in missing)
        print(f'Система: {d.system} {d.release}, RAM {d.ram_gb} ГБ, свободно {d.disk_free_gb} ГБ')
        print(f'GPU: {d.gpu_name or "не обнаружена"}; драйвер: {d.gpu_driver or "неизвестен"}')
        print(f'Компонентов в манифесте: {len(self.manifest)}; требуют проверки: {len(missing)}')
        print(f'Суммарные известные оценки загрузки: {known:.0f} МБ (не смета установки)')
        for s in missing:
            print(f'  {s.id:<23} {self.status(s):<15} {"готов к защищённой загрузке" if s.downloadable else "ручная подготовка SHA-256/файла"}')
        return [{'id': s.id, 'status': self.status(s), 'ready': s.downloadable} for s in missing]

    def _journal(self, kind: str, payload: dict):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'time': time.time(), 'event': kind, **payload}, ensure_ascii=False)+'\n')

    def _install_verified(self, spec: DependencySpec, *, offline_dir: Path | None = None):
        if not spec.sha256:
            raise PermissionDenied(f'{spec.id}: нет закреплённого SHA-256')
        artifact_dir = self.root / 'downloads'
        artifact_dir.mkdir(exist_ok=True)
        if not spec.compatible():
            raise ValueError(f'{spec.id}: файл не совместим с этой ОС/архитектурой/Python')
        basename = artifact_filename(spec)
        artifact = artifact_dir / basename
        if offline_dir:
            source = (offline_dir / basename).resolve()
            if not source.is_relative_to(offline_dir.resolve()) or not source.is_file():
                raise FileNotFoundError(f'Нет офлайн-файла {basename}')
            if sha256_file(source).lower() != spec.sha256.lower():
                raise ValueError('Неверная контрольная сумма офлайн-файла')
            shutil.copy2(source, artifact)
        else:
            if not spec.downloadable:
                raise PermissionDenied(f'Нет проверенного HTTPS URL для {spec.id}')
            self.downloader.download(spec.url, artifact, spec.sha256)
        if spec.artifact == 'wheel':
            self.venv.install_wheel(artifact, spec.sha256)
        elif spec.artifact == 'model':
            target = self.registry.model_path(spec)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact, target)
        elif spec.artifact == 'zip':
            if not spec.target:
                raise ValueError('Для zip нужно указать target')
            target = (self.root / spec.target).resolve()
            if not target.is_relative_to(self.root):
                raise ValueError('Попытка распаковки вне проекта')
            if target.exists():
                raise FileExistsError('Целевая папка уже существует, автоматическое перезаписывание запрещено')
            self.downloader.extract(artifact, target)
        else:
            raise PermissionDenied('Системные установщики требуют ручной проверки и запуска')
        self._journal('applied', {'id': spec.id})

    def apply(self, ids: list[str], *, offline_dir: Path | None = None, include_venv: bool = False):
        selected = [self.manifest.by_id[i] for i in ids]
        if len(ids) != len(set(ids)):
            raise ValueError('Дублирование id')
        for item in selected:
            if not item.compatible():
                raise ValueError(f'{item.id}: требуется {item.supported_os} x64 / CPython {item.python_minor or "системный компонент"}')
            if item.artifact == 'manual' or not item.sha256:
                raise PermissionDenied(f'{item.id} требует ручной настройки и закрепления SHA-256')
            if offline_dir is None and not item.downloadable:
                raise PermissionDenied(f'Не закреплён URL и SHA-256 для {item.id}')
        operations = []
        if include_venv and not self.venv.python().is_file():
            operations.append({'name': 'Создать локальное виртуальное окружение',
                               'action': f'python -m venv {self.venv.path}',
                               'reason': 'Изолировать версии библиотек агента',
                               'benefit': 'Не затрагиваются общесистемные Python-пакеты',
                               'risks': 'Место на диске, создание файлов проекта'})
        for x in selected:
            operations.append({'name': x.id, 'action': f'Получить/проверить SHA-256 {x.sha256}; {x.artifact} -> {x.target}',
                               'reason': x.purpose, 'benefit': x.benefit, 'risks': x.risks})
        if not operations:
            return []
        if not self.gate.approve(operations):
            raise PermissionDenied('Пользователь отклонил операции')
        if include_venv and not self.venv.python().is_file():
            self.venv.create()
            self._journal('venv_created', {})
        done = []
        for item in selected:
            try:
                self._install_verified(item, offline_dir=offline_dir)
                done.append(item.id)
            except Exception as exc:
                self._journal('failed', {'id': item.id, 'error': type(exc).__name__})
                print(f'Установка остановлена на {item.id}: {exc}')
                break
        return done
