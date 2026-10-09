"""Smoke-тесты L4 без Android, Ollama, ChromaDB, YOLO или ONNX."""
import asyncio
import json
from types import SimpleNamespace
import pytest
import numpy as np
import cv2
from game_agent.config import Settings
from game_agent.models import Action, Box, Observation, TextItem
from game_agent.brain import Manager, Worker, Brain
from game_agent.l4.temporal import GameStateVector, GameStateExtractor, TemporalPredictor
from game_agent.l4.dsl import SkillRegistry, DSLInterpreter, DSLParseError
from game_agent.l4.local_vlm import CascadedVLM, LocalVLM
from game_agent.l4.swarm import SwarmBus, SwarmCoordinator
from game_agent.l4.hid import SerialHIDTransport, CalibratedHIDInput, HIDError, HIDWithADBFallback
from game_agent.l4.agent_l4 import Level4Agent


def obs(state="unknown", text=(), boxes=()):
    im = np.zeros((80,160,3), dtype=np.uint8)
    jpeg = cv2.imencode('.jpg',im)[1].tobytes()
    return Observation(160,80,"scene1",jpeg,list(boxes),
                       [TextItem(t,Box(5,5,100,40),.9) for t in text],state, .9 if state!="unknown" else .2)


def test_extractor_unknown_not_zero():
    s = GameStateExtractor().extract(obs(),timestamp=1)
    assert s.hp is None and s.mp is None and s.distance is None


def test_extractor_ocr_and_enemies():
    s = GameStateExtractor().extract(obs(text=["HP 10/100","MP 3/10","Cooldown skill1 2.5s"],
                boxes=[Box(80,20,100,40,"enemy_mage", .97)]), timestamp=1)
    assert s.hp == .1 and s.mp == .3 and s.enemy_mage
    assert s.cooldowns == {"skill1":2.5} and s.distance is not None


def test_predictor_low_hp():
    p = TemporalPredictor(window=10)
    for i in range(10):
        p.add(GameStateVector(timestamp=i*.5, hp=.55-.045*i))
    result=p.predict()
    assert result.hp < .2 and "low_hp_soon" in result.events


def test_predictor_monotonic_and_unknown():
    p = TemporalPredictor()
    assert p.predict().hp is None
    p.add(GameStateVector(1.))
    with pytest.raises(ValueError): p.add(GameStateVector(.5))


def test_dsl_restricted_and_potion():
    sk=SkillRegistry()
    sk.register("use_potion",lambda arg, observation: Action(kind="tap",x=20,y=20,risk="safe",confidence=.95,target=Box(5,5,50,40)))
    dsl=DSLInterpreter(sk)
    r=dsl.interpret("IF enemy_mage AND hp < 20% THEN use_potion('magic_resist')",
                      {"enemy_mage":True,"hp":.12},obs())
    assert r.kind == "tap"
    assert dsl.interpret("IF hp < 20% THEN use_potion('heal')", {"hp":None}, obs()).kind == "wait"
    for evil in ["IF __import__('os') THEN use_potion('heal')",
                 "IF hp < 20% THEN __import__('os')",
                 "IF hp < 20% THEN use_potion(__import__('os'))",
                 "IF hp.__class__ THEN use_potion('heal')"]:
        with pytest.raises(DSLParseError): dsl.interpret(evil,{"hp":.12},obs())


def test_dsl_unknown_skill_wait():
    assert DSLInterpreter(SkillRegistry()).interpret("IF hp < 20% THEN use_potion('heal')",
                {"hp":.1},obs()).kind == "wait"


class VLMStub:
    def __init__(self, confidence): self.confidence=confidence; self.calls=0
    def ask_json(self,*args,**kwargs):
        self.calls+=1
        return {"dsl":"IF False THEN wait()", "confidence":self.confidence}


def test_local_cloud_cascade():
    local,cloud = VLMStub(.2),VLMStub(.9)
    c=CascadedVLM(LocalVLM(backend=local),cloud=cloud,allow_cloud=True)
    c.ask_json(b'png','test')
    assert (local.calls,cloud.calls,c.last_backend)==(1,1,"cloud")
    c2=CascadedVLM(LocalVLM(backend=VLMStub(.2)),cloud=cloud,allow_cloud=False)
    assert c2.ask_json(b'png','test')["confidence"] == 0
    assert cloud.calls == 1


def test_bus_scene_ttl_and_capacity():
    async def runner():
        bus=SwarmBus(maxsize=2)
        for i in range(3):
            await bus.publish("s","t","e",{"i":i},"scene1",10)
        arr=bus.drain("t","scene1",now=10.5)
        assert [m.payload["i"] for m in arr]==[1,2]
        await bus.publish("s","t","e",{},"old",0)
        assert bus.drain("t","scene1",now=10.5)==[]
    asyncio.run(runner())


def test_swarm_scary_wait():
    s=GameStateVector(timestamp=1,hp=.1)
    p=TemporalPredictor()
    p.add(s)
    swarm=SwarmCoordinator(Manager(),Worker(vlm=None),DSLInterpreter(SkillRegistry()),vlm=None)
    goal,act=asyncio.run(swarm.decide(obs(state="battle"),s,p.predict(),now=1))
    assert goal=="combat" and act.kind=="wait"


class FakeSerial:
    def __init__(self):self.writes=[]
    def write(self,d):self.writes.append(d)
    def flush(self): pass
    def readline(self):
        seq=json.loads(self.writes[-1])["seq"]
        return json.dumps({"seq":seq,"ok":True}).encode()
    def close(self):pass


def test_hid_ack_restrictions():
    fake=FakeSerial()
    p=SerialHIDTransport("COM9",connection=fake)
    assert p.send("move",dx=5,dy=-4)["ok"]
    with pytest.raises(HIDError):p.send("move",dx=300,dy=0)
    with pytest.raises(HIDError):p.send("key",code="DELETE")
    with pytest.raises(HIDError):CalibratedHIDInput(p).tap(50,60)


class MockADB:
    def __init__(self):self.calls=[]
    def tap(self,x,y):self.calls.append(("tap",x,y))
    def screenshot_png(self):return cv2.imencode('.png',np.zeros((80,160,3),dtype=np.uint8))[1].tobytes()
    def swipe(self,*args):self.calls.append(("swipe",*args))


def test_hid_adb_fallback():
    adb=MockADB()
    device=HIDWithADBFallback(adb,CalibratedHIDInput(SerialHIDTransport("COM9",connection=FakeSerial())))
    device.tap(30,20)
    assert adb.calls==[("tap",30,20)]


def test_level4_dry_run_integration(tmp_path):
    config=Settings(game_id="mock",memory_dir=str(tmp_path),dry_run=True)
    adb=MockADB()
    brain=Brain(Manager(),Worker(vlm=None))
    model=LocalVLM(backend=VLMStub(0))
    g=Level4Agent(config, device=adb,brain=brain,local_vlm=model,sleep=lambda _:None)
    out=g.step()
    assert out["status"]=="wait" and not adb.calls
    assert "l4_state" in g.memory.recent()[0]


def test_ack_unknown_no_duplicate_adb():
    class TimeoutSerial(FakeSerial):
        def readline(self): return b''
    from game_agent.l4.hid import HIDAckUncertain
    adb=MockADB()
    ser=SerialHIDTransport("COM9", connection=TimeoutSerial())
    hid=CalibratedHIDInput(ser,x=5,y=5,calibrated=True)
    combined=HIDWithADBFallback(adb,hid)
    with pytest.raises(HIDAckUncertain):
        combined.tap(5,5)
    assert not adb.calls
