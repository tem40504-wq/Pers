"""Захват PNG с ADB; видеострим — необязательная оптимизация."""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, Iterator
from .adb_bridge import ADBBridge


@dataclass(frozen=True)
class Frame:
    image: bytes
    timestamp: float
    source: str


class FastCapture:
    def __init__(self, bridge: ADBBridge, stream_provider: Callable | None = None):
        self.bridge, self.stream_provider = bridge, stream_provider

    def get_frame(self) -> Frame:
        # Если нет валидного потока — надёжный screencap.
        if self.stream_provider is not None:
            try:
                candidate = self.stream_provider()
                if isinstance(candidate, bytes) and candidate.startswith(b'\x89PNG\r\n\x1a\n'):
                    return Frame(candidate, time.monotonic(), 'stream')
            except Exception:
                pass
        return Frame(self.bridge.screenshot_png(), time.monotonic(), 'adb_screencap')

    def poll(self, max_frames: int = 10, interval: float = .5) -> Iterator[Frame]:
        for i in range(max_frames):
            start = time.monotonic()
            yield self.get_frame()
            remaining = interval - (time.monotonic() - start)
            if remaining > 0 and i + 1 < max_frames:
                time.sleep(remaining)
