"""Сбор проверенного офлайн-набора. Без явного разрешения сеть недоступна."""
from __future__ import annotations
import shutil
from pathlib import Path
from .manifest import DependencyManifest, artifact_filename
from .permissions import BatchPermissionGate, PermissionDenied
from .pc_downloader import PCDownloader


class OfflineBootstrap:
    def __init__(self, manifest: DependencyManifest, gate: BatchPermissionGate, downloader=None):
        self.manifest, self.gate = manifest, gate
        self.downloader = downloader or PCDownloader()

    def download_bundle(self, ids: list[str], directory: str | Path):
        specs = [self.manifest.by_id[x] for x in ids]
        if not all(s.downloadable for s in specs):
            raise PermissionDenied('Офлайн-набор требует закреплённых HTTPS URL и SHA-256')
        ops = [{'name': x.id, 'action': f'GET {x.url} -> SHA-256 {x.sha256}',
                'reason': x.purpose, 'benefit': x.benefit, 'risks': x.risks} for x in specs]
        if not self.gate.approve(ops):
            raise PermissionDenied('Оператор отклонил скачивание')
        dest = Path(directory)
        dest.mkdir(parents=True, exist_ok=True)
        result = []
        for s in specs:
            basename = artifact_filename(s)
            result.append(self.downloader.download(s.url, dest / basename, s.sha256))
        return result
