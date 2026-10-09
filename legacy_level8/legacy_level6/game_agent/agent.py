"""Цикл Sense–Think–Act с Manager/Worker и записью результатов каждого шага."""
from __future__ import annotations
import logging
import time

from .action import ActionExecutor
from .adb import ADBDevice
from .brain import Brain, Manager, Worker
from .config import Settings
from .explore import UIExplorer
from .memory import Memory, self_reflection
from .models import Action
from .perception import Perception
from .vlm import VLM

LOG = logging.getLogger("game_agent")


class GameAgent:
    def __init__(self, cfg: Settings, device=None, perception=None, brain=None,
                 memory=None, executor=None, clock=time.monotonic, sleep=time.sleep):
        self.cfg = cfg
        self.clock = clock
        self.sleep = sleep
        self.device = device or ADBDevice(cfg.adb_path, cfg.serial)
        self.vision = perception or Perception(cfg.enable_ocr, cfg.enable_yolo,
                                              cfg.yolo_weights, cfg.ocr_period)
        self.vlm = VLM(cfg.vlm_provider, cfg.vlm_model, cfg.vlm_url,
                       cfg.api_key, cfg.openai_url)
        self.brain = brain or Brain(Manager(cfg.manager_period, cfg.user_goal),
                                    Worker(self.vlm, cfg.vlm_cooldown))
        self.memory = memory or Memory(cfg.memory_dir, cfg.game_id, cfg.enable_chroma)
        self.executor = executor or ActionExecutor(self.device, cfg.safe_zones,
                                                   cfg.confidence_threshold, sleep=sleep)
        self.explorer = UIExplorer(str(self.memory.root / "ui_map.json"), cfg.safe_zones,
                                   cfg.max_explore_actions) if cfg.explore else None
        self.was_game_over = False
        self.no_change = 0

    def choose_action(self, obs, now):
        """Совместимая точка подключения новых стратегий (L3 по умолчанию)."""
        return self.brain.decide(obs, lessons=self.memory.recent_lessons(), now=now)

    def extra_event(self, obs, action, status) -> dict:
        """Необязательные данные для JSONL. В L3 сохраняется прежнее поведение."""
        return {}

    def step(self) -> dict:
        before = self.device.screenshot_png()
        obs = self.vision.observe(before, now=self.clock())
        if self.explorer:
            self.explorer.register(obs)
        goal, action = self.choose_action(obs, self.clock())
        if self.explorer and not obs.game_over:
            action = self.explorer.propose(obs)
        if self.no_change >= 4:
            action = Action(reason="Нет прогресса в последних 4 действиях")
        if obs.game_over:
            action = Action(reason="Поражение: ввод остановлен")
        result = self.executor.execute(action, obs, dry_run=self.cfg.dry_run)
        status = result["status"]
        # Связанный снимок до/после; проверка только при реально сделанном действии.
        if status.startswith("executed"):
            self.sleep(.15)
            after = self.device.screenshot_png()
            delta = self.vision.change(before, after)
            next_obs = self.vision.observe(after, now=self.clock())
            self.no_change = self.no_change + 1 if delta < .012 else 0
        else:
            after, delta, next_obs = before, 0., obs
        event = self.memory.record({
            "state": obs.state, "scene_id": obs.scene_id, "goal": goal,
            "action": action.as_dict(), "status": status,
            "text": " | ".join(t.text for t in obs.text[:25]),
            "change": round(delta, 4), "next_scene": next_obs.scene_id,
            **self.extra_event(obs, action, status)
        }, before=before, after=after)
        if self.explorer and status.startswith("executed"):
            self.explorer.connect(obs, next_obs, action, status)
        if next_obs.game_over and not self.was_game_over:
            lesson = self_reflection(self.memory, self.vlm)
            LOG.warning("REFLECTION: %s", lesson["lesson"])
        self.was_game_over = next_obs.game_over
        return {"goal": goal, "state": obs.state, "action": action.kind,
                "status": status, "delta": delta, "id": event["id"]}

    def run(self, max_steps=None) -> None:
        max_steps = self.cfg.max_steps if max_steps is None else max_steps
        count = 0
        while max_steps == 0 or count < max_steps:
            start = self.clock()
            try:
                res = self.step()
                LOG.info("step=%d %s", count + 1, res)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                LOG.exception("Ошибка цикла: %s. Остановка для проверки", exc)
                break
            count += 1
            # 500 мс — целевой период запуска, но OCR/VLM/ADB могут быть медленнее.
            self.sleep(max(0, self.cfg.worker_period - (self.clock() - start)))
