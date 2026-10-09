import unittest,tempfile,asyncio
from pathlib import Path
from mobile_core.contracts import Observation,Detection,Decision,Mode
from mobile_core.security import EmergencyStop,SecurityCore,AuditLogger,PermissionRequired
from mobile_core.memory import MobileMemory
from mobile_core.tactician import Tactician,SkillLibrary
from mobile_core.perception import MobilePerception
from mobile_core.agent import MobileAgent
from mobile_core.offload import ComputeOffloadProxy

class FakeBridge:
    def frame(self):return b'fake jpeg'
    def status(self):return {'width':1080,'height':2200,'scene':'menu','thermal_c':39}
    def gesture(self,decision):self.last=decision;return {'accepted':True}

class MobileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.mem=MobileMemory(str(self.root/'data.db'));self.addCleanup(self.mem.close)
        self.stop=EmergencyStop();self.stop.arm(True)
        self.sec=SecurityCore(self.stop)
        self.sec.safe_boxes=[(0,0,1080,2200)]
        self.skills=SkillLibrary('examples/skills.json')
    def test_default_stopped(self):self.assertTrue(EmergencyStop().stopped)
    def test_expired(self):self.stop._last-=301;self.assertFalse(self.stop.allowed())
    def test_panic(self):self.stop.panic();self.assertFalse(self.stop.allowed())
    def test_risk(self):
        d=Decision('tap','купить что-то',skill_id='open_map',x=100,y=200,confidence=.98)
        self.assertFalse(self.sec.validate(d,Observation(),True))
    def test_unknown_skill(self):
        d=Decision('tap','меню',skill_id='fake',x=100,y=200,confidence=.98)
        self.assertFalse(self.sec.validate(d,Observation(),False))
    def test_safe_box(self):
        self.sec.safe_boxes=[(30,30,50,50)]
        d=Decision('tap','меню',skill_id='open_map',x=100,y=200,confidence=.98)
        self.assertFalse(self.sec.validate(d,Observation(),True))
    def test_approved(self):
        d=Decision('tap','карта',skill_id='open_map',x=100,y=200,confidence=.98)
        self.assertTrue(self.sec.validate(d,Observation(),True))
    def test_permission_n(self):
        self.assertFalse(self.sec.request('package','dep','benefit','risk',callback=lambda _: 'N'))
    def test_footprint(self):
        self.mem.add('G','action',{'status':'ok'},[1.,0.]);self.assertEqual(len(self.mem.recent('G')),1)
        self.assertEqual(len(self.mem.search('G',[1.,0.])),1)
    def test_private_memory(self):
        with self.assertRaises(ValueError):self.mem.add('G','x',{'token':'123'})
    def test_chained_audit(self):
        p=self.root/'audit.jsonl';secret=b'z'*32
        audit=AuditLogger(p,secret);audit.append('action',{'x':1})
        self.assertTrue(AuditLogger(p,secret).verify())
    def test_tactician_wait(self):
        t=Tactician(self.skills)
        self.assertEqual(t.decide(Observation()).kind,'wait')
    def test_tactician_known_target(self):
        t=Tactician(self.skills)
        o=Observation(detections=[Detection('safe_map_button',.95,(10,10,20,20))])
        self.assertEqual(t.decide(o).skill_id,'open_map')
    def test_no_gesture_dry_run(self):
        bridge=FakeBridge();agent=MobileAgent(bridge,MobilePerception(),Tactician(self.skills),self.sec,self.mem,dry_run=True)
        agent.resume();asyncio.run(agent.run(steps=2));self.assertFalse(hasattr(bridge,'last'))
    def test_no_gesture_panic(self):
        bridge=FakeBridge();self.sec.emergency.panic()
        agent=MobileAgent(bridge,MobilePerception(),Tactician(self.skills),self.sec,self.mem,dry_run=False)
        self.assertFalse(agent.resume())
    def test_offload_fallback(self):
        async def local(x):return {'scene':'local'}
        proxy=ComputeOffloadProxy('http://127.0.0.1:55555','token',enabled=True,timeout=.05)
        out=asyncio.run(proxy.analyze(b'jpeg',local))
        self.assertEqual(out['scene'],'local')

if __name__=='__main__':unittest.main()
