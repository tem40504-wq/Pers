"""Три слоя зрения: OpenCV; EasyOCR; YOLO (опционально), VLM по триггеру через Brain."""
from __future__ import annotations
import hashlib
import io
import re
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .models import Box, Observation, TextItem

LOSS = re.compile(r"\b(game\s*over|defeat|defeated|you\s+lost|failed|поражени[ея]|проигрыш|вы\s+проиграли)\b", re.I)
BATTLE = re.compile(r"\b(battle|fight|attack|combat|бой|атака|сражени[ея])\b", re.I)
QUEST = re.compile(r"\b(quest|mission|task|квест|задани[ея]|мисси[яию])\b", re.I)


class Perception:
    def __init__(self, enable_ocr=False, enable_yolo=False, yolo_weights=None, ocr_period=3.0):
        self.reader = None
        self.detector = None
        self.ocr_period = ocr_period
        self.last_ocr_at = float("-inf")
        self.previous_text: list[TextItem] = []
        self.previous_scene = None
        if enable_ocr:
            try:
                import easyocr
                # Без явного Y не разрешаем EasyOCR скачивать веса при старте.
                self.reader = easyocr.Reader(["ru", "en"], gpu=False, download_enabled=False)
            except FileNotFoundError as exc:
                raise RuntimeError("OCR-веса отсутствуют. Нужна ручная установка после согласования; продолжите без --ocr") from exc
            except ImportError as exc:
                raise RuntimeError("Установите pip install easyocr или выключите --ocr") from exc
        if enable_yolo:
            if not yolo_weights or not Path(yolo_weights).is_file():
                raise ValueError("Для --yolo нужны веса игрового детектора: --weights path/to/best.pt")
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError("Установите pip install ultralytics") from exc
            self.detector = YOLO(yolo_weights)

    @staticmethod
    def from_png(data: bytes) -> np.ndarray:
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Не удалось декодировать PNG")
        return frame

    @staticmethod
    def to_jpeg(frame: np.ndarray, max_side: int = 1280) -> bytes:
        h, w = frame.shape[:2]
        scale = min(1., max_side / max(h, w))
        if scale < 1:
            frame = cv2.resize(frame, (round(w * scale), round(h * scale)))
        buf = io.BytesIO()
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(buf, "JPEG", quality=80)
        return buf.getvalue()

    @staticmethod
    def signature(frame: np.ndarray) -> str:
        # Хеш миниатюры дает воспроизводимый идентификатор визуального состояния.
        gray = cv2.cvtColor(cv2.resize(frame, (32, 24)), cv2.COLOR_BGR2GRAY)
        level = gray > float(gray.mean())
        return hashlib.blake2s(level.tobytes(), digest_size=8).hexdigest()

    @staticmethod
    def change(before: bytes, after: bytes) -> float:
        a, b = Perception.from_png(before), Perception.from_png(after)
        x = cv2.cvtColor(cv2.resize(a, (160, 90)), cv2.COLOR_BGR2GRAY)
        y = cv2.cvtColor(cv2.resize(b, (160, 90)), cv2.COLOR_BGR2GRAY)
        return float(np.mean(cv2.absdiff(x, y)) / 255.0)

    def cv_candidates(self, frame: np.ndarray) -> list[Box]:
        # Контуры = геометрические кандидаты, НЕ доказанные безопасные кнопки.
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 65, 130)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        h, w = frame.shape[:2]
        boxes = []
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            if 34 <= bw <= w * .50 and 16 <= bh <= h * .25 and bw * bh > 900:
                boxes.append(Box(x, y, x + bw, y + bh, "unknown_ui", 0.30))
        boxes.sort(key=lambda b: (b.y1, b.x1))
        return boxes[:50]

    def yolo_candidates(self, frame: np.ndarray) -> list[Box]:
        if self.detector is None:
            return []
        result = self.detector.predict(frame, verbose=False, conf=.45)[0]
        out = []
        for coords, score, label in zip(result.boxes.xyxy.cpu().numpy(),
                                        result.boxes.conf.cpu().numpy(),
                                        result.boxes.cls.cpu().numpy()):
            x1, y1, x2, y2 = map(int, coords)
            out.append(Box(x1, y1, x2, y2, str(result.names[int(label)]), float(score)))
        return out

    def ocr(self, frame: np.ndarray) -> list[TextItem]:
        if self.reader is None:
            return []
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        entries = self.reader.readtext(rgb, detail=1, paragraph=False)
        found = []
        for pts, txt, conf in entries:
            x1 = int(min(p[0] for p in pts))
            x2 = int(max(p[0] for p in pts))
            y1 = int(min(p[1] for p in pts))
            y2 = int(max(p[1] for p in pts))
            found.append(TextItem(str(txt), Box(x1, y1, x2, y2, "text", float(conf)), float(conf)))
        return found

    def observe(self, png: bytes, now: float | None = None) -> Observation:
        now = time.monotonic() if now is None else now
        frame = self.from_png(png)
        h, w = frame.shape[:2]
        sid = self.signature(frame)
        errors = []
        boxes = self.cv_candidates(frame)
        if self.detector is not None:
            try:
                boxes.extend(self.yolo_candidates(frame))
            except Exception as exc:
                errors.append(f"YOLO: {str(exc)[:120]}")
        scene_changed = sid != self.previous_scene
        if self.reader is not None and (now - self.last_ocr_at >= self.ocr_period or
                                        (scene_changed and now - self.last_ocr_at >= 1.5)):
            try:
                self.previous_text = self.ocr(frame)
                self.last_ocr_at = now
            except Exception as exc:
                errors.append(f"OCR: {str(exc)[:120]}")
                self.previous_text = []
        text = list(self.previous_text) if self.reader is not None else []
        self.previous_scene = sid
        words = " ".join(t.text for t in text if t.confidence >= .25)
        lost = bool(LOSS.search(words))
        state = "game_over" if lost else ("battle" if BATTLE.search(words) else
                    ("quest" if QUEST.search(words) else "unknown"))
        confidence = .97 if lost else (.78 if state != "unknown" else .20)
        return Observation(w, h, sid, self.to_jpeg(frame), boxes, text, state,
                           confidence, lost, self.reader is not None and not errors, errors)
