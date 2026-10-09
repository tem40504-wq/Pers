"""Пример подключения Voyager Skill Library без привязки к её реализации."""
from __future__ import annotations
from ..models import Action, Observation
from .dsl import SkillRegistry


def register_approved_potions(registry: SkillRegistry, labels: dict[str, str]):
    """labels: {'heal': 'heal_potion'}.
    Навык действует ТОЛЬКО при наличии обученной детекции нужного объекта.
    """
    def use_potion(name: str | None, obs: Observation) -> Action:
        label = labels.get(name or "")
        if not label:
            return Action(reason="Название предмета не разрешено")
        for box in obs.candidate_boxes:
            if box.label == label and box.confidence >= .92:
                x, y = box.center
                return Action(kind="tap", x=x, y=y, target=box,
                              risk="safe", confidence=box.confidence,
                              reason="Разрешённый навык Skill Library: лечение")
        return Action(reason="Не обнаружена подтверждённая иконка зелья")
    registry.register("use_potion", use_potion)
    registry.register("wait", lambda arg, obs: Action(reason="Ожидание по DSL"))
