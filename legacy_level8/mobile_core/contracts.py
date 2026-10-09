"""Версионированные структуры данных между Android, Termux и ПК."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time

class Mode(str, Enum):
    AUTONOMOUS = 'MODE_AUTONOMOUS'
    DEBUG = 'MODE_DEBUG'
    OFFLOAD = 'MODE_OFFLOAD'

@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]

@dataclass
class Observation:
    ts: float = field(default_factory=time.monotonic)
    width: int = 1080
    height: int = 2400
    detections: list[Detection] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    audio_events: list[str] = field(default_factory=list)
    hp: float | None = None
    mp: float | None = None
    thermal_c: float | None = None
    scene: str = 'unknown'
    screenshot_jpeg: bytes | None = None

@dataclass(frozen=True)
class Decision:
    kind: str  # wait/tap/swipe; запрет произвольного ADB или shell
    reason: str
    skill_id: str = ''
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    duration_ms: int = 250
    risk: str = 'safe'
    confidence: float = 0.0

@dataclass(order=True)
class Task:
    priority: int
    created: float
    name: str = field(compare=False)
    params: dict[str, Any] = field(default_factory=dict, compare=False)
