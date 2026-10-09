"""Скачивание с докачкой, SHA-256 и безопасной распаковкой архивов."""
from __future__ import annotations
import hashlib
import os
import shutil
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from .manifest import official_https


class DownloadError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _safe_destination(root: Path, name: str) -> Path:
    if '\\' in name or name.startswith('/') or ':' in name:
        raise DownloadError('Небезопасное имя файла в архиве')
    dest = (root / name).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise DownloadError('Выход из папки распаковки запрещён')
    return dest


class PCDownloader:
    def __init__(self, timeout: int = 25, retries: int = 3, progress=None):
        self.timeout = timeout
        self.retries = max(1, min(retries, 3))
        # progress(received_bytes, total_bytes_or_none, bytes_per_second)
        self.progress = progress

    def download(self, url: str, output: str | Path, sha256: str, mirrors: tuple[str, ...] = ()) -> Path:
        if not sha256 or len(sha256) != 64 or any(c not in '0123456789abcdefABCDEF' for c in sha256):
            raise DownloadError('Нужен заранее подтверждённый SHA-256')
        urls = (url,) + tuple(mirrors)
        if not all(official_https(u) for u in urls):
            raise DownloadError('Скачивание разрешено только с проверенных HTTPS-доменов')
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and sha256_file(output).lower() == sha256.lower():
            return output
        part = output.with_suffix(output.suffix + '.part')
        failure = None
        for endpoint in urls:
            for attempt in range(self.retries):
                current = part.stat().st_size if part.exists() else 0
                req = urllib.request.Request(endpoint,
                                             headers={'User-Agent': 'UniversalGameAgent-Bootstrap/1.0',
                                                      **({'Range': f'bytes={current}-'} if current else {})})
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        if not official_https(resp.geturl()):
                            raise DownloadError('Перенаправление на недоверенный сайт')
                        resumed = current and resp.status == 206
                        total_header = resp.headers.get('Content-Length') if getattr(resp, 'headers', None) else None
                        total = (int(total_header) + (current if resumed else 0)) if total_header and total_header.isdigit() else None
                        transferred = current if resumed else 0
                        started = time.monotonic()
                        with part.open('ab' if resumed else 'wb') as f:
                            while True:
                                chunk = resp.read(1024 * 1024)
                                if not chunk:
                                    break
                                f.write(chunk)
                                transferred += len(chunk)
                                if self.progress:
                                    speed = max(0, transferred-(current if resumed else 0)) / max(.001, time.monotonic()-started)
                                    self.progress(transferred, total, speed)
                    if sha256_file(part).lower() != sha256.lower():
                        # Ошибочный файл нельзя считать завершённым.
                        part.unlink(missing_ok=True)
                        raise DownloadError('SHA-256 не совпал с закреплённым значением')
                    os.replace(part, output)
                    return output
                except (OSError, DownloadError, urllib.error.URLError) as exc:
                    failure = exc
                    if attempt + 1 < self.retries:
                        time.sleep(min(2 ** attempt, 4))
        raise DownloadError(f'Не удалось получить подтверждённый файл: {failure}')

    def extract(self, archive: str | Path, destination: str | Path) -> Path:
        archive, destination = Path(archive), Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                items = z.infolist()
                if len(items) > 20000 or sum(i.file_size for i in items) > 20 * 1024**3:
                    raise DownloadError('Архив превышает безопасный лимит распаковки')
                for item in items:
                    target = _safe_destination(destination, item.filename)
                    # Ссылки/особые Unix-файлы в ZIP запрещены.
                    kind = (item.external_attr >> 16) & 0o170000
                    if kind not in (0, 0o100000, 0o040000):
                        raise DownloadError('В ZIP есть запрещённая запись')
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(item) as src, target.open('wb') as dst:
                            shutil.copyfileobj(src, dst)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as t:
                items = t.getmembers()
                if len(items) > 20000 or sum(i.size for i in items) > 20 * 1024**3:
                    raise DownloadError('Архив превышает безопасный лимит распаковки')
                for item in items:
                    target = _safe_destination(destination, item.name)
                    if item.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif item.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        src = t.extractfile(item)
                        if src is None:
                            raise DownloadError('Невозможно прочитать файл TAR')
                        with src, target.open('wb') as dst:
                            shutil.copyfileobj(src, dst)
                    else:
                        raise DownloadError('Символические ссылки и устройства в TAR запрещены')
        else:
            raise DownloadError('Поддерживаются только ZIP и TAR')
        return destination
