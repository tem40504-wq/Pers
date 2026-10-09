"""Мобильный цикл: все жесты только из AccessibilityController; ADB здесь отсутствует."""
from __future__ import annotations
import asyncio, time
from .contracts import Mode,Decision
from .security import EmergencyStop,SecurityCore
from .perception import MobilePerception
from .tactician import Tactician
from .bridge import AccessibilityController,BridgeError
from .memory import MobileMemory

class MobileAgent:
    def __init__(self,controller:AccessibilityController,perception:MobilePerception,
                 tactician:Tactician,security:SecurityCore,memory:MobileMemory,
                 game='generic',mode:Mode=Mode.AUTONOMOUS,dry_run=True,offload=None):
        self.controller=controller;self.perception=perception;self.tactician=tactician
        self.security=security;self.memory=memory;self.mode=mode;self.game=game;self.dry_run=dry_run
        self.offload=offload
        self.paused=True;self.last_observation=None;self.last_decision=None
        self._slow_data={};self._busy=False;self.fast_interval=.1;self.slow_interval=1.
    def pause(self):self.paused=True
    def resume(self):
        if not self.security.emergency.allowed():return False
        self.paused=False;return True
    def panic(self):self.security.emergency.panic();self.paused=True
    def postprocess_decision(self, obs, decision):
        # Обратная совместимость: базовый агент всегда возвращает прежнее решение.
        return decision

    def on_cycle_complete(self, obs, decision, result, frame):
        # Необязательная точка расширения для тестовых логов Level 8.
        pass

    def status(self):
        o=self.last_observation
        return {'mode':self.mode.value,'paused':self.paused,'panic':self.security.emergency.stopped,
          'dry_run':self.dry_run,'scene':o.scene if o else 'unknown','hp':o.hp if o else None,
          'decision':self.last_decision.kind if self.last_decision else None,
          'thermal_c':o.thermal_c if o else None}
    async def _slow(self,frame:bytes,meta:dict):
        try:
            o=await asyncio.to_thread(self.perception.observe,frame,meta,True)
            if self.mode==Mode.OFFLOAD and self.offload is not None:
                async def local(image):
                    return self.perception.vlm(image) if self.perception.vlm else {'scene':'unknown','confidence':0.}
                result=await self.offload.analyze(frame,local)
                if isinstance(result,dict) and result.get('confidence',0)>=.7:
                    o.scene=str(result.get('scene','unknown'))
            self._slow_data={'texts':o.texts,'audio':o.audio_events,'scene':o.scene}
        except Exception:pass
        finally:self._busy=False
    async def run(self,steps=0):
        cycle=0;last_slow=0.;tasks=set()
        try:
            while (steps==0 or cycle<steps):
                began=time.monotonic()
                if not self.security.emergency.allowed():
                    self.paused=True
                if self.paused:
                    await asyncio.sleep(.2)
                    if steps:break
                    continue
                try:
                    # Телефон сам поставляет кадры; нельзя ADB screencap.
                    frame=await asyncio.to_thread(self.controller.frame)
                    meta=await asyncio.to_thread(self.controller.status)
                except BridgeError:
                    self.pause()
                    await asyncio.sleep(.3)
                    if steps:break
                    continue
                obs=self.perception.observe(frame,meta,False)
                obs.texts=list(self._slow_data.get('texts',[]))
                obs.audio_events=list(self._slow_data.get('audio',[]))
                if obs.scene=='unknown' and self._slow_data.get('scene'):
                    obs.scene=str(self._slow_data['scene'])
                self.last_observation=obs
                # Тепловое ограничение относится к измерению, предоставленному Android.
                if obs.thermal_c is not None and obs.thermal_c>=45.0:
                    self.fast_interval=.5
                else:self.fast_interval=.1
                if obs.thermal_c is None or obs.thermal_c<45.0:
                    if time.monotonic()-last_slow>=self.slow_interval and not self._busy:
                        last_slow=time.monotonic();self._busy=True
                        t=asyncio.create_task(self._slow(frame,meta));tasks.add(t);t.add_done_callback(tasks.discard)
                d=self.postprocess_decision(obs,self.tactician.decide(obs))
                self.last_decision=d
                known=d.skill_id in self.tactician.skills.skills
                permitted=self.security.validate(d,obs,known)
                status='wait'
                if d.kind!='wait':
                    if not permitted:status='blocked'
                    elif self.dry_run:status='dry_run'
                    else:
                        # После решения повторно смотрим на EmergencyStop непосредственно перед жестом.
                        if self.security.emergency.allowed() and not self.paused:
                            try:
                                reply=await asyncio.to_thread(self.controller.gesture,d)
                                status='accepted' if reply.get('accepted') else 'rejected'
                            except BridgeError:status='bridge_error';self.pause()
                        else:status='stopped'
                if self.security.audit:
                    self.security.audit.append('action',{'kind':d.kind,'skill':d.skill_id,'status':status})
                self.memory.add(self.game,'action',{'skill':d.skill_id,'status':status,'reason':d.reason})
                self.on_cycle_complete(obs,d,status,frame)
                cycle+=1
                await asyncio.sleep(max(0.,self.fast_interval-(time.monotonic()-began)))
        finally:
            for t in tasks:t.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
