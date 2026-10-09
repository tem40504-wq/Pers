"""Уровень 4 как расширение старого GameAgent: базовый цикл не дублируется."""
from __future__ import annotations
import asyncio
import logging

from ..agent import GameAgent
from ..models import Action
from .temporal import GameStateExtractor, TemporalPredictor
from .dsl import DSLInterpreter, SkillRegistry
from .local_vlm import LocalVLM, CascadedVLM
from .swarm import SwarmCoordinator
from .skill_adapter import register_approved_potions

LOG = logging.getLogger(__name__)


class Level4Agent(GameAgent):
    def __init__(self, cfg, *, hp_roi=None, mp_roi=None, skill_registry=None,
                 local_vlm=None, cloud_vlm=None, allow_cloud=False, legacy_vlm=None,
                 rules=None, **kwargs):
        super().__init__(cfg, **kwargs)
        self.extractor = GameStateExtractor(hp_roi, mp_roi)
        self.temporal = TemporalPredictor(window=10, horizon=.5)
        self.registry = skill_registry or SkillRegistry()
        # Без явной детекции heal_potion по YOLO использовать зелье нельзя.
        if skill_registry is None:
            register_approved_potions(self.registry, {})
        self.dsl = DSLInterpreter(self.registry)
        cascade = CascadedVLM(
            local_vlm or LocalVLM(), cloud=cloud_vlm,
            legacy=legacy_vlm, threshold=.7, allow_cloud=allow_cloud)
        self.swarm = SwarmCoordinator(self.brain.manager, self.brain.worker,
                                      self.dsl, cascade, rules,
                                      vlm_cooldown=cfg.vlm_cooldown)
        self.last_state = None
        self.last_prediction = None

    def choose_action(self, obs, now):
        try:
            self.last_state = self.extractor.extract(obs, timestamp=now)
            self.temporal.add(self.last_state)
            self.last_prediction = self.temporal.predict()
            return asyncio.run(self.swarm.decide(
                obs, self.last_state, self.last_prediction,
                now=now, lessons=self.memory.recent_lessons()))
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            # Временный сбой L4 не ломает старый Manager-Worker.
            LOG.exception("L4 не смог принять решение, используем L3: %s", exc)
            return super().choose_action(obs, now)

    def extra_event(self, obs, action, status):
        state = self.last_state
        pred = self.last_prediction
        if not state or not pred:
            return {}
        # Числовой контекст попадает в JSONL/Chroma через прежний Memory.record.
        return {"l4_state": {"hp": state.hp, "mp": state.mp,
                             "distance": state.distance, "cooldowns": state.cooldowns,
                             "enemy_mage": state.enemy_mage},
                "l4_prediction": pred.as_dict()}
