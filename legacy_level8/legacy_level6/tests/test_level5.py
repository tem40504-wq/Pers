"""Offline tests L5: без Android, API, загрузки весов или установки пакетов."""
import asyncio
from threading import Event
import time

import numpy as np
import cv2
import pytest

from game_agent.models import Action, Box, Observation
from game_agent.l4.temporal import GameStateVector
from game_agent.l5.world_model import WorldModel
from game_agent.l5.audio import AudioPerception
from game_agent.l5.meta_adapter import MetaAdapter, LabeledRegion
from game_agent.l5.behavior import HumanBehaviorGenerator
from game_agent.l5.operator import OperatorAssistant
from game_agent.l5.dashboard import XAI_Dashboard
from game_agent.l5.agent_l5 import PanicExecutor, AudioSwarmAdapter
from game_agent.l4.swarm import SwarmBus
from game_agent.l4.security import PermissionGate, PermissionDenied, DEPENDENCIES


def verified_action():
    return Action(kind="tap",x=50,y=30,risk="safe",confidence=.99,
                  target=Box(30,10,70,50,label="heal_icon"))


def states(t,hp):
    return GameStateVector(timestamp=t,hp=hp,mp=.7)


def test_world_model_untrained_fallback():
    wm=WorldModel()
    action=verified_action()
    assert wm.predict_next(states(1,.5),action).confidence==0
    plan=wm.planning(states(1,.5),[action],steps=6)
    assert not plan.used_model and plan.action==action


def test_world_model_uses_real_transitions_only():
    wm=WorldModel()
    action=verified_action()
    for i in range(18):
        wm.learn(states(i*3+1,.4),action,states(i*3+1.5,.5))
    estimate=wm.predict_next(states(58,.5),action)
    assert estimate.confidence>.65 and estimate.next_state.hp>.5
    result=wm.planning(states(58,.5),[action],steps=5)
    assert result.used_model and result.rollout_steps==5
    with pytest.raises(ValueError):wm.planning(states(1,.5),[action],steps=12)


def test_world_model_skips_missing_measurement():
    wm=WorldModel()
    wm.learn(GameStateVector(1),verified_action(),states(2,.2))
    assert not wm.transitions


class FakeAudio:
    def classify(self, pcm):return {"enemy_attack":.95, "victory":.2}


def test_audio_no_model_and_cooldown():
    silent=AudioPerception()
    assert silent.process(np.zeros(1600,dtype=np.float32),now=1)==[]
    p=AudioPerception(FakeAudio())
    assert [x.kind for x in p.process(np.zeros(1600,dtype=np.float32),now=10)]==["enemy_attack"]
    assert not p.process(np.zeros(1600,dtype=np.float32),now=10.1)
    assert len(p.drain(now=11))==1
    assert not p.drain(now=11)


def test_audio_rejects_bad_samples():
    with pytest.raises(ValueError):AudioPerception(FakeAudio()).process(np.zeros(100),16000)
    with pytest.raises(ValueError):AudioPerception(FakeAudio()).process(np.ones(2000)*3,16000)


def test_meta_adapter_few_shots():
    img=np.zeros((60,60,3),dtype=np.uint8)
    img[:,:,:]=(0,130,180)
    adapter=MetaAdapter()
    samples=[LabeledRegion(img,(5,5,25,25),"quest") for _ in range(6)]
    assert adapter.fit(samples)==1
    label,confidence=adapter.classify(img,(5,5,25,25))
    assert label=="quest" and confidence>.95
    assert MetaAdapter().classify(img,(5,5,25,25))==(None,0.)


def test_behavior_no_install_and_endpoints():
    gen=HumanBehaviorGenerator(seed=4)
    trace=gen.generate_human_swipe((0,0),(100,200))
    assert len(trace)==24
    assert (trace[0].x,trace[0].y)==(0,0)
    assert (trace[-1].x,trace[-1].y)==(100,200)
    with pytest.raises(ValueError):gen.train_gan([[(0,0),(1,1)]],epochs=1)


def test_operator_explains_unknown_facts_without_hallucination():
    op=OperatorAssistant(verbosity=2)
    assert "пока нет" in op.explain_current_state()
    op.observe(GameStateVector(1,hp=.5,mp=None), action=Action(reason="неизвестный навык"),goal="quest")
    assert "50%" in op.explain_current_state()
    assert "не определено" in op.explain_current_state()
    assert "не распознан" in op.answer_operator_question("Почему не используешь ульту?")
    assert op.generate_tutorial("Комбо",evidence_count=1,source="3 кадра") is None
    assert op.generate_tutorial("Комбо",evidence_count=3,source="сравнение 3 кадров")
    assert op.generate_tutorial("Комбо",evidence_count=3,source="повтор") is None
    with pytest.raises(ValueError):op.set_verbosity(4)


def test_feedback_blocks_then_panics():
    op=OperatorAssistant()
    action=Action(kind="tap",x=20,y=20,risk="safe",confidence=.99,reason="use potion",target=Box(10,10,40,40,"heal_potion"))
    op.receive_feedback("Не пей зелье, беги!")
    assert op.safe_override(action).kind=="wait"
    op.receive_feedback("PANIC STOP")
    assert op.panic_event.is_set()
    assert op.safe_override(verified_action()).kind=="wait"


def test_dashboard_panic_blocks_executor():
    class Legacy:
        def __init__(self):self.calls=0
        def execute(self,*args,**kwargs):
            self.calls+=1
            return {"status":"executed"}
    op=OperatorAssistant()
    dash=XAI_Dashboard(op)
    legacy=Legacy()
    executor=PanicExecutor(legacy,op.panic_event)
    assert executor.execute(Action(),None)["status"]=="executed"
    assert dash.stop()["stopped"]
    assert executor.execute(Action(),None)["status"]=="blocked:panic_stop"
    assert legacy.calls==1


def test_dashboard_app_offline():
    pytest.importorskip("fastapi")
    app=XAI_Dashboard(OperatorAssistant()).app()
    paths={r.path for r in app.routes}
    assert {"/api/frame","/api/status","/api/panic","/api/feedback","/api/ask"}<=paths


def test_swarm_audio_bus_hook():
    class Stub:
        def __init__(self):self.bus=SwarmBus()
        async def decide(self,obs,state,prediction,now,lessons=None):
            incoming=self.bus.drain('tactician',obs.scene_id,now)
            return "combat", [x.kind for x in incoming]
    stereo=AudioPerception(FakeAudio())
    stereo.process(np.zeros(1600,dtype=np.float32),now=5)
    adapter=AudioSwarmAdapter(Stub(),stereo,XAI_Dashboard(OperatorAssistant()))
    obs=Observation(100,100,"sceneA",b"",state="battle")
    goal,received=asyncio.run(adapter.decide(obs,states(5,.4),None,5))
    assert goal=="combat" and "danger" in received


def test_permissiongate_denied_new_dependencies():
    assert all(k in DEPENDENCIES for k in ("fastapi","uvicorn","sounddevice","tflite_runtime","torch"))
    calls=[]
    gate=PermissionGate(ask=lambda prompt:"N",output=lambda text:None,
                         runner=lambda *args,**kwargs:calls.append(args))
    gate.available=lambda name:False
    assert gate.ensure_dependency("fastapi",required=False) is False
    with pytest.raises(PermissionDenied):gate.ensure_dependency("torch",required=True)
    assert not calls
