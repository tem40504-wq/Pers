"""Единые типы данных. Модель не может создавать произвольные ADB-команды."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    label: str = "unknown_ui"
    confidence: float = 0.0

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    def contains(self, x: int, y: int, margin: int = 0) -> bool:
        return self.x1 + margin <= x <= self.x2 - margin and self.y1 + margin <= y <= self.y2 - margin

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TextItem:
    text: str
    box: Box
    confidence: float

    def as_dict(self) -> dict:
        return {"text": self.text, "box": self.box.as_dict(), "confidence": self.confidence}


@dataclass(frozen=True)
class Action:
    kind: str = "wait"
    x: int | None = None
    y: int | None = None
    x1: int | None = None
    y1: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 400
    confidence: float = 0.0
    reason: str = ""
    risk: str = "uncertain"
    target: Box | None = None  # Доверенная локальная область для дополнительной проверки

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "Action":
        if not isinstance(data, dict):
            raise ValueError("Ответ VLM не JSON-объект")
        kind = data.get("action")
        if kind not in ("tap", "swipe", "wait"):
            raise ValueError("Неразрешённое действие")
        confidence = data.get("confidence", 0)
        if type(confidence) not in (int, float) or not (0 <= confidence <= 1):
            raise ValueError("Некорректная confidence")
        risk = data.get("risk", "uncertain")
        if risk not in ("safe", "uncertain", "prohibited"):
            raise ValueError("Некорректная risk")
        names = {"tap": ("x", "y"), "swipe": ("x1", "y1", "x2", "y2"), "wait": ()}[kind]
        for name in names:
            if type(data.get(name)) is not int:
                raise ValueError(f"Координата {name} должна быть int")
        duration = data.get("duration_ms", 400)
        if type(duration) is not int or not 100 <= duration <= 2000:
            raise ValueError("duration_ms вне диапазона 100–2000")
        reason = data.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("reason должен быть строкой")
        return cls(kind=kind, confidence=float(confidence), risk=risk,
                   duration_ms=duration, reason=reason[:300],
                   **{name: data[name] for name in names})

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Observation:
    width: int
    height: int
    scene_id: str
    image_jpeg: bytes = field(repr=False)
    candidate_boxes: list[Box] = field(default_factory=list)
    text: list[TextItem] = field(default_factory=list)
    state: str = "unknown"
    confidence: float = 0.0
    game_over: bool = False
    ocr_available: bool = False
    errors: list[str] = field(default_factory=list)

    def compact(self) -> dict:
        return {"screen": [self.width, self.height], "scene_id": self.scene_id,
                "state": self.state, "confidence": round(self.confidence, 3),
                "game_over": self.game_over, "ocr_available": self.ocr_available,
                "text": [t.as_dict() for t in self.text[:35]],
                "boxes": [b.as_dict() for b in self.candidate_boxes[:35]],
                "errors": self.errors[-3:]}
