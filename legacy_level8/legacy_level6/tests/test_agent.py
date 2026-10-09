"""Офлайн-тесты: ни телефон, ни OCR, ни VLM не нужны."""
import json
import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from game_agent.action import ActionExecutor, bezier_points
from game_agent.agent import GameAgent
from game_agent.brain import Brain, Manager, Worker
from game_agent.config import Settings
from game_agent.explore import UIExplorer
from game_agent.memory import Memory, local_embedding, self_reflection
from game_agent.models import Action, Box, Observation, TextItem
from game_agent.perception import Perception


class MockADB:
    def __init__(self, png=None):
        self.calls = []
        self.png = png
    def tap(self, x, y):
        self.calls.append(("tap", x, y))
    def swipe(self, *args):
        self.calls.append(("swipe", *args))
    def screenshot_png(self):
        return self.png


def sample_png():
    img = np.zeros((120, 200, 3), dtype=np.uint8)
    cv2.rectangle(img, (40, 40), (160, 80), (255, 255, 255), 2)
    return cv2.imencode('.png', img)[1].tobytes()


def sample_obs(text=(), confidence=.9, state="unknown"):
    items = [TextItem(s, Box(42, 40, 158, 80, "text", confidence), confidence) for s in text]
    return Observation(200, 120, "abc", b"JPEG", [Box(40, 40, 160, 80, "unknown_ui", .3)],
                       items, state, .2, state=="game_over", bool(text))


def test_action_json_strict():
    with pytest.raises(ValueError):
        Action.parse({"action":"shell", "confidence":1, "risk":"safe"})
    with pytest.raises(ValueError):
        Action.parse({"action":"tap", "x":True, "y":4, "confidence":1, "risk":"safe"})
    with pytest.raises(ValueError):
        Action.parse({"action":"tap", "x":20, "y":4, "confidence":2, "risk":"safe"})


def test_bezier_endpoints():
    pts = bezier_points((0, 10), (100, 90), rng=random.Random(1))
    assert pts[0] == (0, 10) and pts[-1] == (100, 90)
    assert len(pts) == 16


def test_safe_tap_and_jitter():
    adb = MockADB()
    executor = ActionExecutor(adb, rng=random.Random(10), sleep=lambda x: None)
    obs = sample_obs(["start"])
    action = Action(kind="tap", x=100, y=60, confidence=.95, risk="safe", target=Box(40,40,160,80))
    result = executor.execute(action, obs, dry_run=False)
    assert result["status"] == "executed"
    assert adb.calls[0][0] == "tap"
    assert abs(adb.calls[0][1]-100) <= 15


def test_dry_run_untouched():
    adb = MockADB()
    executor = ActionExecutor(adb, sleep=lambda x: None)
    act = Action(kind="tap", x=100, y=60, confidence=.99, risk="safe", target=Box(40,40,160,80))
    assert executor.execute(act, sample_obs(["start"]), dry_run=True)["status"] == "dry_run"
    assert not adb.calls


def test_block_unknown_without_zone():
    adb = MockADB()
    executor = ActionExecutor(adb, sleep=lambda x: None)
    act = Action(kind="tap", x=100, y=60, confidence=.99, risk="safe")
    assert executor.execute(act, sample_obs(["start"]), dry_run=False)["status"] == "blocked:point"
    assert not adb.calls


def test_block_risky_ocr():
    adb = MockADB()
    executor = ActionExecutor(adb, sleep=lambda x: None)
    act = Action(kind="tap", x=100, y=60, confidence=.99, risk="safe", target=Box(40,40,160,80))
    assert executor.execute(act, sample_obs(["Купить"]), dry_run=False)["status"] == "blocked:risk"


def test_swipe_fallback():
    adb = MockADB()
    executor = ActionExecutor(adb, safe_zones=((0,0,199,119),), sleep=lambda x: None, rng=random.Random(2))
    act = Action(kind="swipe", x1=60, y1=60, x2=130, y2=70,
                 confidence=.95, risk="safe")
    result = executor.execute(act, sample_obs(["start"]), dry_run=False)
    assert result["status"] == "executed:linear_fallback"
    assert adb.calls[0][0] == "swipe"


def test_vision_dimensions_and_diff():
    png = sample_png()
    p = Perception()
    obs = p.observe(png, now=0)
    assert (obs.width, obs.height) == (200, 120)
    assert not obs.game_over
    assert Perception.change(png, png) == 0


def test_manager_period():
    manager = Manager(period=10.0, user_goal="фарм")
    obs = sample_obs(state="battle")
    assert manager.update(obs, now=0) == "combat"
    obs.state = "quest"
    assert manager.update(obs, now=5) == "combat"
    assert manager.update(obs, now=11) == "quest"


def test_worker_without_vlm():
    work = Worker(vlm=None)
    act = work.decide(sample_obs(["Start"]), "quest")
    assert act.kind == "tap" and act.target is not None
    assert Worker(vlm=None).decide(sample_obs([]), "explore").kind == "wait"


def test_memory_saves_images(tmp_path):
    m = Memory(str(tmp_path), "testgame")
    png = sample_png()
    row = m.record({"action":"tap", "status":"executed", "change":0.2}, png, png)
    assert Path(row["before_path"]).exists()
    assert Path(row["after_path"]).exists()
    assert len(m.recent()) == 1
    assert len(m.log_path.read_text(encoding="utf8").splitlines()) == 1


def test_embeddings_stable():
    a = local_embedding("battle hp low")
    assert a == local_embedding("battle hp low") and len(a) == 256
    assert a != local_embedding("forest dragon")


def test_memory_chroma_mock(tmp_path):
    class Collection:
        def upsert(self, **kw): self.data = kw
        def query(self, **kw): return {"documents": [["something"]]}
    class Client:
        def __init__(self): self.col = Collection()
        def get_or_create_collection(self, name): return self.col
    c = Client()
    m = Memory(str(tmp_path), "testgame", enable_chroma=True, chroma_client=c)
    m.record({"action": "tap", "status": "executed"})
    assert len(c.col.data["embeddings"][0]) == 256
    assert m.similar("tap") == ["something"]


def test_reflection_fallback(tmp_path):
    m = Memory(str(tmp_path), "testgame")
    m.record({"action":"tap", "status":"executed"}, sample_png(), sample_png())
    lesson = self_reflection(m, None)
    assert lesson["confidence"] == .15
    assert m.recent_lessons()


def test_explore_requires_safe_zone(tmp_path):
    with pytest.raises(ValueError):
        UIExplorer(str(tmp_path / "ui.json"), ())


def test_explore_ui_map(tmp_path):
    explore = UIExplorer(str(tmp_path / "ui.json"), ((0,0,199,119),), rng=random.Random(3))
    obs = sample_obs(["Start"])
    action = explore.propose(obs)
    assert action.kind == "tap"
    explore.register(obs)
    explore.connect(obs, obs, action, "executed")
    data = json.loads((tmp_path / "ui.json").read_text(encoding="utf8"))
    assert data["nodes"] and data["edges"]


def test_game_agent_integration_mock(tmp_path):
    device = MockADB(sample_png())
    cfg = Settings(game_id="testgame", memory_dir=str(tmp_path), dry_run=True)
    brain = Brain(Manager(), Worker(vlm=None))
    g = GameAgent(cfg, device=device, brain=brain, sleep=lambda _: None)
    result = g.step()
    assert result["status"] == "wait"
    assert len(g.memory.recent()) == 1
    assert not device.calls
