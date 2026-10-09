"""Проверка и хранение веса модели; отсутствующие веса не выдаются за готовые."""
from __future__ import annotations
from pathlib import Path
from .manifest import DependencySpec
from .pc_downloader import sha256_file


class PCModelRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def model_path(self, spec: DependencySpec) -> Path:
        if spec.category != 'model' or not spec.target:
            raise ValueError('Это не модель')
        path = (self.root / spec.target).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Путь за пределами проекта')
        return path

    def status(self, spec: DependencySpec) -> str:
        path = self.model_path(spec)
        if not path.exists() or not path.is_file():
            return 'missing'
        if not spec.sha256:
            return 'unverified'
        return 'verified' if sha256_file(path).lower() == spec.sha256.lower() else 'hash_mismatch'

    def fallback(self, primary: DependencySpec, backup: DependencySpec) -> Path | None:
        if self.status(primary) == 'verified':
            return self.model_path(primary)
        if self.status(backup) == 'verified':
            return self.model_path(backup)
        return None
