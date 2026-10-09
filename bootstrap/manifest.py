"""Манифест в JSON-совместимом YAML: разбирается стандартной библиотекой Python."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import platform
import sys
import struct

_SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')
_ALLOWED = ('python.org', 'pypi.org', 'files.pythonhosted.org', 'nvidia.com',
            'developer.nvidia.com', 'download.pytorch.org', 'dl.google.com',
            'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com', 'huggingface.co')


def official_https(url: str) -> bool:
    u = urlparse(url)
    return bool(u.hostname and u.scheme == 'https' and u.username is None and u.password is None
            and any(u.hostname == x or u.hostname.endswith('.'+x) for x in _ALLOWED))


@dataclass(frozen=True)
class DependencySpec:
    id: str
    category: str
    version: str
    import_name: str | None
    executable: str | None
    source: str
    url: str | None
    sha256: str | None
    size_mb: float | None
    purpose: str
    benefit: str
    risks: str
    missing_impact: str
    required: bool
    artifact: str
    target: str | None
    supported_os: str | None = None
    python_minor: str | None = None

    def compatible(self) -> bool:
        if self.supported_os and (platform.system() != self.supported_os
                                  or struct.calcsize('P') != 8
                                  or platform.machine().lower() not in {'amd64', 'x86_64'}):
            return False
        if self.python_minor and (f'{sys.version_info.major}.{sys.version_info.minor}' != self.python_minor
                                  or sys.implementation.name != 'cpython'
                                  or bool(__import__('sysconfig').get_config_var('Py_GIL_DISABLED'))):
            return False
        return True

    @property
    def downloadable(self) -> bool:
        return bool(self.url and self.sha256 and _SHA256.fullmatch(self.sha256)
                    and official_https(self.url))


class DependencyManifest:
    def __init__(self, path: str | Path):
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        if doc.get('schema_version') != 1:
            raise ValueError('Неизвестная версия манифеста')
        self.components = [DependencySpec(**x) for x in doc['components']]
        ids = [x.id for x in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError('Повторяющийся id в манифесте')
        for s in self.components:
            if s.url and not official_https(s.url):
                raise ValueError(f'Недоверенный адрес источника {s.id}')
            if s.sha256 is not None and not _SHA256.fullmatch(s.sha256):
                raise ValueError(f'Недопустимый SHA-256 {s.id}')
            if s.artifact not in {'manual', 'wheel', 'zip', 'model'}:
                raise ValueError(f'Неизвестный тип файла {s.id}')
        self.by_id = {x.id: x for x in self.components}
        self.profiles = doc.get('profiles', {})
        for ids in self.profiles.values():
            if len(ids) != len(set(ids)) or any(i not in self.by_id for i in ids):
                raise ValueError('Некорректный профиль манифеста')

    def __len__(self):
        return len(self.components)


def artifact_filename(spec: DependencySpec) -> str:
    # pip разбирает имя wheel как distribution-version-tags; префикс ломает его.
    name = Path(spec.target or 'artifact.bin').name
    return name if spec.artifact == 'wheel' else spec.id + '--' + name
