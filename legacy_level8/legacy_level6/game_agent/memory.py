"""Эпизодическая и векторная память, хранение скриншотов вне ChromaDB."""
from __future__ import annotations
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import uuid
from typing import Any


def local_embedding(text: str, dims=256) -> list[float]:
    """Детерминированное локальное embedding без скачивания весов.

    Это лексическая проекция (feature hashing), НЕ полноценная семантическая модель.
    Для глубокого поиска позже подключается sentence-transformers / внешние embeddings.
    """
    vector = [0.] * dims
    for token in re.findall(r"[\w]+", text.lower(), flags=re.UNICODE):
        h = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dims
        sign = 1 if h[4] % 2 == 0 else -1
        vector[idx] += sign
    norm = math.sqrt(sum(x*x for x in vector)) or 1.
    return [v / norm for v in vector]


class Memory:
    def __init__(self, base_dir="runtime", game_id="generic", enable_chroma=False,
                 chroma_client=None):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", game_id):
            raise ValueError("GAME_ID: только a-z, A-Z, 0-9, _ и -")
        self.game_id = game_id
        self.root = Path(base_dir) / game_id
        self.frames = self.root / "frames"
        self.frames.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "episodes.jsonl"
        self.lessons_path = self.root / "lessons.jsonl"
        self.events: deque[dict] = deque(maxlen=10)
        self.lessons: deque[str] = deque(maxlen=100)
        self.collection = None
        if self.lessons_path.is_file():
            for line in self.lessons_path.read_text(encoding="utf8").splitlines()[-100:]:
                try:
                    self.lessons.append(json.loads(line)["lesson"])
                except (ValueError, KeyError):
                    pass
        if enable_chroma:
            if chroma_client is None:
                try:
                    import chromadb
                except ImportError as exc:
                    raise RuntimeError("Для --chroma: pip install chromadb") from exc
                chroma_client = chromadb.PersistentClient(path=str(self.root / "chroma"))
            self.collection = chroma_client.get_or_create_collection(name="game_experiences")

    def snapshot(self, png: bytes, label="frame") -> str:
        """Не сохраняем неподконтрольные имена путей; только случайный UUID."""
        path = self.frames / f"{label}_{uuid.uuid4().hex}.png"
        path.write_bytes(png)
        return str(path)

    def record(self, event: dict, before: bytes | None = None,
               after: bytes | None = None) -> dict:
        row = dict(event)
        row.setdefault("id", uuid.uuid4().hex)
        row.setdefault("time", datetime.now(timezone.utc).isoformat())
        row["game"] = self.game_id
        if before:
            row["before_path"] = self.snapshot(before, "before")
        if after:
            row["after_path"] = self.snapshot(after, "after")
        with self.log_path.open("a", encoding="utf8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self.events.append(row)
        if self.collection is not None:
            self._index(row)
        return row

    @staticmethod
    def _document(row: dict) -> str:
        return (f"game={row.get('game')} state={row.get('state')} goal={row.get('goal')} "
                f"action={row.get('action')} status={row.get('status')} "
                f"OCR={row.get('text', '')} result={row.get('change')} "
                f"lesson={row.get('lesson', '')} "
                f"L4_state={json.dumps(row.get('l4_state', {}), ensure_ascii=False)} "
                f"L4_prediction={json.dumps(row.get('l4_prediction', {}), ensure_ascii=False)}")[:8000]

    def _index(self, row: dict) -> None:
        doc = self._document(row)
        self.collection.upsert(ids=[row["id"]], documents=[doc],
                               embeddings=[local_embedding(doc)],
                               metadatas=[{
                                   "game": str(self.game_id),
                                   "status": str(row.get("status", "")),
                                   "before_path": str(row.get("before_path", "")),
                                   "after_path": str(row.get("after_path", "")),
                               }])

    def recent(self) -> list[dict]:
        return list(self.events)

    def recent_lessons(self) -> list[str]:
        return list(self.lessons)[-5:]

    def similar(self, query: str, limit=5) -> list[str]:
        if self.collection is None:
            return []
        resp = self.collection.query(query_embeddings=[local_embedding(query)],
                                     n_results=max(1, limit), include=["documents"])
        return resp.get("documents", [[]])[0]

    def add_lesson(self, lesson: str, confidence: float, evidence_ids: list[str]) -> dict:
        row = {"id": uuid.uuid4().hex, "game": self.game_id,
               "time": datetime.now(timezone.utc).isoformat(),
               "lesson": lesson[:1500], "confidence": round(float(confidence), 3),
               "evidence": evidence_ids, "status": "reflection"}
        with self.lessons_path.open("a", encoding="utf8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.lessons.append(row["lesson"])
        if self.collection is not None:
            self._index(row)
        return row


def self_reflection(memory: Memory, vlm=None) -> dict:
    """При поражении анализируем последние 10 пар до/после. Вывод — гипотеза, не факт."""
    events = memory.recent()[-10:]
    if not events:
        return memory.add_lesson("Причина поражения неизвестна: истории нет", .1, [])
    summary = [{k: e.get(k) for k in ("id", "state", "action", "status", "change", "text")}
               for e in events]
    lesson, confidence = ("Недостаточно данных, требуется ручная проверка лога", .15)
    if vlm is not None:
        # Компонуем ровно последние 10 кадров ПОСЛЕ действий в одно изображение.
        try:
            from PIL import Image, ImageDraw
            import io
            previews = []
            for ev in events:
                p = ev.get("after_path") or ev.get("before_path")
                if p and Path(p).is_file():
                    im = Image.open(p).convert("RGB")
                    im.thumbnail((320, 180))
                    previews.append(im.copy())
            if previews:
                canvas = Image.new("RGB", (640, 200 * math.ceil(len(previews)/2)), "#222222")
                draw = ImageDraw.Draw(canvas)
                for i, im in enumerate(previews):
                    x, y = (i % 2) * 320, (i // 2) * 200
                    canvas.paste(im, (x, y + 18))
                    draw.text((x+5, y+2), f"Step {i+1}", fill="white")
                buffer = io.BytesIO()
                canvas.save(buffer, format="JPEG", quality=80)
                answer = vlm.ask_json(buffer.getvalue(),
                    "Это последовательность кадров перед Game Over. "
                    f"История: {json.dumps(summary, ensure_ascii=False)[:6000]}. "
                    "Сделай осторожный вывод о ВОЗМОЖНОЙ причине поражения и уроке. "
                    'Верни JSON {"lesson":"проверяемая гипотеза", "confidence":0.0}. "'
                    "Не приписывай невидимых фактов игре.",
                    schema={"type":"object", "properties": {
                        "lesson":{"type":"string"}, "confidence":{"type":"number"}},
                        "required":["lesson","confidence"], "additionalProperties":False})
                candidate = answer.get("lesson", "")
                val = answer.get("confidence", 0)
                if isinstance(candidate, str) and isinstance(val, (int, float)) and candidate:
                    lesson, confidence = candidate, min(.9, max(0., float(val)))
        except Exception:
            pass
    return memory.add_lesson(lesson, confidence, [e.get("id", "") for e in events])
