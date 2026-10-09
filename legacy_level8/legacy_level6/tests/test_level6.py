"""Level6: автономные тесты без телефона, Интернета или установки зависимостей."""
import io
import tempfile
import time
import unittest
from pathlib import Path

from game_agent.l6.continual import ContinualLearner, Experience
from game_agent.l6.federated import FederatedHub, SkillVector, UIAnchor
from game_agent.l6.physics import PhysicsWorldModel
from game_agent.l6.toolforge import SafePythonSubset, ToolForge, ToolTest, UnsafeTool
from game_agent.l6.affective import AffectiveEngine


class GateStub:
    def __init__(self, answer):self.answer=answer;self.requests=[]
    def require_external_action(self,**kwargs):
        self.requests.append(kwargs)
        return self.answer


class TestReplay(unittest.TestCase):
    def setUp(self):self.d=tempfile.TemporaryDirectory()
    def tearDown(self):self.d.cleanup()
    def exp(self,n):return Experience({'hp':n/100},'heal',1.0,{'hp':min(1,n/100+.1)})
    def test_profiles_isolated_and_persistent(self):
        a=ContinualLearner(self.d.name,capacity=10)
        a.select_game('GameA');a.record(self.exp(10));a.save()
        a.select_game('GameB');self.assertEqual(len(a.replay),0)
        a.record(self.exp(20));a.select_game('GameA')
        self.assertEqual(len(a.replay),1)
        self.assertEqual(a.replay[0].state['hp'],.1)
    def test_replay_retains_past(self):
        a=ContinualLearner(self.d.name,replay_ratio=1.0)
        a.select_game('GameA');a.record(self.exp(10))
        self.assertIn(self.exp(10), a.sample([self.exp(20)],2))
    def test_invalid_id(self):
        a=ContinualLearner(self.d.name)
        with self.assertRaises(ValueError):a.select_game('../escape')
    def test_no_regression(self):
        a=ContinualLearner(self.d.name);a.select_game('G')
        self.assertIsNone(a.train_verified([self.exp(10)],lambda batch:object(),lambda _:0.1,.2))
    def test_weights_require_permission(self):
        a=ContinualLearner(self.d.name);a.select_game('G')
        with self.assertRaises(PermissionError):a.register_weights('a.pth')


class TestFederation(unittest.TestCase):
    def setUp(self):self.h=FederatedHub(b'z'*32)
    def sample(self):return SkillVector('GameA','heal',tuple(.1 for _ in range(16)),.9)
    def test_no_permission(self):
        with self.assertRaises(PermissionError):self.h.envelope([self.sample()])
    def test_signed_quarantine(self):
        e=self.h.envelope([self.sample()],approved=True)
        self.assertEqual(self.h.ingest(e),1)
        self.assertEqual(len(self.h.accepted),0)
        with self.assertRaises(PermissionError):self.h.accept(0)
        self.h.accept(0,approved=True)
        self.assertEqual(len(self.h.accepted),1)
    def test_tampering_and_replay(self):
        e=self.h.envelope([self.sample()],approved=True)
        e['payload']['skills'][0]['confidence']=0
        with self.assertRaises(ValueError):self.h.ingest(e)
        e=self.h.envelope([self.sample()],approved=True)
        self.h.ingest(e)
        with self.assertRaises(ValueError):self.h.ingest(e)
    def test_disallow_private_text(self):
        e=self.h.envelope([self.sample()],approved=True)
        e['payload']['skills'][0]['password']='abc'
        e['mac']=self.h._mac(e['payload'])
        with self.assertRaises(ValueError):self.h.ingest(e)
    def test_screen_map_only_safe_labels(self):
        a=UIAnchor('GameA','heal_button',.4,.2)
        e=self.h.envelope([self.sample()],approved=True,screen_map=[a])
        self.assertEqual(self.h.ingest(e),2)
        self.assertEqual(len(self.h.ui_quarantine),1)
        with self.assertRaises(ValueError):
            self.h.envelope([],approved=True,screen_map=[UIAnchor('GameA','account_email',.4,.2)])

    def test_network_must_use_https(self):
        h=FederatedHub(b'z'*32,endpoint='http://example.com/exchange')
        with self.assertRaises(ValueError):h.exchange([self.sample()],gate=GateStub(True))


class TestPhysics(unittest.TestCase):
    def test_projectile(self):
        m=PhysicsWorldModel()
        t=m.predict_trajectory((0,0,10,10),(1,0,0),pixels_per_meter=10,initial_height_m=4)
        self.assertGreater(t.flight_seconds,.8)
        self.assertAlmostEqual(t.points_3d[-1][2],0)
        self.assertGreater(t.landing_screen_px[0],5)
    def test_ricochet(self):
        outgoing=PhysicsWorldModel.ricochet_velocity((1,0,-10),(0,0,1),.5)
        self.assertEqual(outgoing,(1.0,0.0,5.0))
    def test_uncalibrated(self):
        with self.assertRaises(ValueError):PhysicsWorldModel().predict_trajectory((0,0,5,5),(1,2,3),pixels_per_meter=0,initial_height_m=4)


class TestForge(unittest.TestCase):
    ok='def tool(inputs):\n    damage = inputs["base"] - inputs["armor"]\n    return max(0, damage)\n'
    def test_calculator(self):
        s=SafePythonSubset(self.ok)
        self.assertEqual(s.run({'base':10,'armor':3}),7)
    def test_code_attack_rejected(self):
        attacks=[
            'import os\ndef tool(inputs): return 5',
            'def tool(inputs):\n    return __import__("os").system("whoami")',
            'def tool(inputs):\n    while True: pass',
            'def tool(inputs):\n    return (1).__class__',
            'def tool(inputs):\n    return 10 ** 1000000',
        ]
        for attack in attacks:
            with self.subTest(attack=attack),self.assertRaises((UnsafeTool,SyntaxError)):SafePythonSubset(attack)
    def test_approval_only(self):
        gate=GateStub(False);f=ToolForge(gate)
        f.propose('damage_calc',self.ok,[ToolTest({'base':10,'armor':3},7)])
        self.assertFalse(f.activate('damage_calc'))
        with self.assertRaises(PermissionError):f.call('damage_calc',{'base':3,'armor':2})
        gate.answer=True;self.assertTrue(f.activate('damage_calc'))
        self.assertEqual(f.call('damage_calc',{'base':2,'armor':3}),0)
    def test_synthesis_does_not_activate(self):
        gate=GateStub(True);f=ToolForge(gate)
        f.synthesize('damage_calc','compute damage',lambda _:self.ok,[ToolTest({'base':3,'armor':2},1)])
        with self.assertRaises(PermissionError):f.call('damage_calc',{'base':3,'armor':2})
        self.assertEqual(len(gate.requests),0)

    def test_unauthorized_remote_side_effect(self):
        f=ToolForge(GateStub(True))
        with self.assertRaises(UnsafeTool):
            f.propose('readfile','def tool(inputs):\n    return open("secrets")',[ToolTest({},'x')])


class TestAffective(unittest.TestCase):
    def test_optin(self):
        a=AffectiveEngine()
        a.record_typing(100,.1);a.record_voice_level(.99)
        self.assertEqual(len(a.paces),0)
        self.assertEqual(len(a.voice_levels),0)
    def test_frequent_stop(self):
        a=AffectiveEngine()
        a.record_stop(100);a.record_stop(120)
        self.assertEqual(a.suggest_style(125).name,'concise')
    def test_operator_override(self):
        a=AffectiveEngine();a.set_operator_verbosity(3)
        a.record_stop(100);a.record_stop(120)
        self.assertEqual(a.suggest_style(125).suggested_verbosity,3)


if __name__=='__main__':unittest.main()
