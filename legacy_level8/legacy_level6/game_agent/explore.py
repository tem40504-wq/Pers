"""Исследование UI только в координатах, которые владелец явно разрешил."""
from __future__ import annotations
import json
from pathlib import Path
import random
from .models import Action, Observation, Box
from .action import RISKY


class UIExplorer:
    def __init__(self, save_path: str, zones: tuple[tuple[int,int,int,int], ...],
                 max_actions=10, rng: random.Random | None = None):
        if not zones:
            raise ValueError("Для исследования укажите хотя бы одну --safe-zone")
        self.path = Path(save_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.zones = [Box(*z) for z in zones]
        self.max_actions = max_actions
        self.rng = rng or random.Random()
        self.used = 0
        self.data = {"nodes": {}, "edges": []}
        if self.path.is_file():
            self.data = json.loads(self.path.read_text(encoding="utf8"))

    def register(self, obs: Observation) -> None:
        self.data["nodes"].setdefault(obs.scene_id, {
            "state": obs.state,
            "text": [t.text for t in obs.text[:30]],
            "boxes": [b.as_dict() for b in obs.candidate_boxes[:20]]})
        self.save()

    def propose(self, obs: Observation) -> Action:
        if self.used >= self.max_actions or obs.game_over:
            return Action(reason="Лимит исследований исчерпан")
        if not obs.ocr_available:
            return Action(reason="Для автопоиска нужен работающий OCR")
        if any(RISKY.search(t.text) for t in obs.text):
            return Action(reason="На экране обнаружена потенциально опасная операция")
        # Случайный выбор из известных CV-кандидатов ВНУТРИ согласованной зоны.
        candidates = []
        for box in obs.candidate_boxes:
            x, y = box.center
            if any(z.contains(x, y, margin=18) for z in self.zones):
                if not any(RISKY.search(t.text) and t.box.contains(x, y, -8) for t in obs.text):
                    candidates.append((x, y, box))
        if not candidates:
            return Action(reason="Нет геометрических кандидатов в безопасных зонах")
        x, y, box = self.rng.choice(candidates)
        return Action(kind="tap", x=x, y=y, confidence=.80,
                      risk="safe", reason="Исследование согласованной зоны", target=box)

    def connect(self, src: Observation, dst: Observation, action: Action, result: str) -> None:
        self.register(dst)
        self.data["edges"].append({"from": src.scene_id, "to": dst.scene_id,
                                   "action": action.as_dict(), "result": result,
                                   "changed": src.scene_id != dst.scene_id})
        if result.startswith("executed"):
            self.used += 1
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf8")
