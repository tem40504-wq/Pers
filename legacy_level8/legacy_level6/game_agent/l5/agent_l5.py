"""Level5Agent: адаптер над существующим L4; L3/L4 цикл не переписывается."""
from __future__ import annotations
import asyncio
from collections import Counter
import logging
import queue
import re
import threading
import time

from ..models import Action
from ..l4.agent_l4 import Level4Agent
from .audio import AudioPerception
from .world_model import WorldModel
from .operator import OperatorAssistant
from .dashboard import XAI_Dashboard

LOG=logging.getLogger(__name__)

class PanicExecutor:
    """Не изменяет старый ActionExecutor; блокирует новые команды до делегирования."""
    def __init__(self, legacy, event):
        self.legacy=legacy
        self.event=event

    def execute(self, action, obs, dry_run=True):
        if self.event.is_set():
            return {"status":"blocked:panic_stop", "reason":"Аварийная остановка"}
        return self.legacy.execute(action,obs,dry_run=dry_run)

class ReportingBus:
    """Прокси уже существующей asyncio шины, без изменений её логики."""
    def __init__(self,legacy,dashboard):
        self.legacy=legacy
        self.dashboard=dashboard

    async def publish(self, source,target,kind,payload,scene_id,timestamp):
        self.dashboard.push_swarm(source,target,kind,payload)
        return await self.legacy.publish(source,target,kind,payload,scene_id,timestamp)

    def drain(self,*args,**kwargs):return self.legacy.drain(*args,**kwargs)
    def channel(self,*args,**kwargs):return self.legacy.channel(*args,**kwargs)

class AudioSwarmAdapter:
    """Звуковые события добавляются до старых Scout/Logistic/Tactician."""
    def __init__(self, legacy, audio, dashboard):
        self.legacy=legacy
        self.audio=audio
        self.bus=ReportingBus(legacy.bus,dashboard)
        legacy.bus=self.bus

    async def decide(self,obs,state,prediction,now,lessons=None):
        for event in self.audio.drain(now=now):
            if event.kind in ("enemy_attack", "low_hp_warning"):
                kind="danger" if event.kind=="enemy_attack" else "low_hp"
            else:
                kind="audio_notice"
            await self.bus.publish("audio","tactician",kind,
                 {"cue":event.kind,"confidence":event.confidence},obs.scene_id,now)
        return await self.legacy.decide(obs,state,prediction,now,lessons)

class AudioWorker:
    """Нельзя блокировать callback аудиодрайвера нейросетевым инференсом."""
    def __init__(self,perception):
        self.perception=perception
        self.queue=queue.Queue(maxsize=3)
        self.quit=threading.Event()
        self.thread=None

    def submit(self,pcm,rate):
        try:self.queue.put_nowait((pcm,rate))
        except queue.Full:
            try:self.queue.get_nowait()
            except queue.Empty:pass
            try:self.queue.put_nowait((pcm,rate))
            except queue.Full:pass

    def start(self):
        def loop():
            while not self.quit.is_set():
                try:pcm,rate=self.queue.get(timeout=.2)
                except queue.Empty:continue
                try:self.perception.process(pcm,rate)
                except Exception as ex:LOG.warning("Аудиоклассификация пропущена: %s",ex)
        self.thread=threading.Thread(target=loop,daemon=True,name="AudioWorker")
        self.thread.start()

    def close(self):self.quit.set()

class Level5Agent(Level4Agent):
    """Добавляет мониторинг и обучение. Любая ошибка возвращает старый выбор."""
    def __init__(self,cfg,*,audio=None,operator=None,dashboard=None,**kwargs):
        super().__init__(cfg,**kwargs)
        self.panic_event=threading.Event()
        self.operator=operator or OperatorAssistant(1,self.panic_event)
        # Выравниваем флаг даже когда оператор был внедрён извне.
        self.panic_event=self.operator.panic_event
        self.dashboard=dashboard or XAI_Dashboard(self.operator,self.panic_event)
        self.audio=audio or AudioPerception()
        self.swarm=AudioSwarmAdapter(self.swarm,self.audio,self.dashboard)
        self.world=WorldModel(horizon_s=.5)
        self._pending_action=None
        self._pending_state=None
        self._last_plan=None
        self._last_obs=None
        self._mechanic_evidence=Counter()
        self.planning_skills=[]  # (имя, аргумент), только зарегистрированные навыки
        self.executor=PanicExecutor(self.executor,self.panic_event)

    def add_planning_skill(self,name,arg=None):
        """Включить проверенный навык как альтернативу для model-based planning."""
        if name not in self.registry._skills:
            raise ValueError("Навык не зарегистрирован в Skill Library")
        self.planning_skills.append((name,arg))

    def choose_action(self,obs,now):
        if self.panic_event.is_set():
            return "остановка",Action(reason="PANIC STOP")
        self._last_obs=obs
        # Подсказка только по многократно прочитанному тексту; без догадок VLM.
        for text_item in obs.text:
            if text_item.confidence >= .88 and re.search(r"combo|комбо|удержив|hold|double.tap|двойное нажат",text_item.text,re.I):
                key=text_item.text.strip()[:100]
                self._mechanic_evidence[key]+=1
                hint=self.operator.generate_tutorial(key,self._mechanic_evidence[key],"повторный OCR")
                if hint:LOG.info("ПОДСКАЗКА: %s",hint)
        self.dashboard.annotate(obs.image_jpeg,obs.candidate_boxes)
        # Существующий TemporalBrain + Swarm + DSL + Worker fallback.
        goal, old_action=super().choose_action(obs,now)
        try:
            candidates=[old_action]
            # Дополнительные действия разрешено предлагать только доверенным
            # навыкам Skill Library, а не произвольным координатам VLM.
            for name,arg in self.planning_skills:
                if name in self.registry._skills:
                    candidates.append(self.registry.invoke(name,arg,obs))
            self._last_plan=self.world.planning(self.last_state,candidates,steps=6,fallback=old_action)
            action=self._last_plan.action if self._last_plan.used_model else old_action
        except Exception as ex:
            LOG.warning("WorldModel недоступна, fallback L4: %s",ex)
            self._last_plan=None
            action=old_action
        action=self.operator.safe_override(action)
        self._pending_state=self.last_state
        self._pending_action=action
        summary=self._last_plan.explanation if self._last_plan else "Резервный L4"
        self.operator.observe(self.last_state,self.last_prediction,action,goal,summary)
        if self.operator.verbosity:
            LOG.info("OPERATOR: %s",self.operator.explain_decision(action))
        return goal,action

    def extra_event(self,obs,action,status):
        original=super().extra_event(obs,action,status)
        original["l5"]={"model_used":bool(self._last_plan and self._last_plan.used_model),
                       "rollout":self._last_plan.rollout_steps if self._last_plan else 0,
                       "operator_verbosity":self.operator.verbosity,
                       "panic":self.panic_event.is_set()}
        return original

    def step(self):
        if self.panic_event.is_set():
            return {"status":"blocked:panic_stop"}
        result=super().step()  # Старый Sense–Think–Act без изменений.
        if result.get("status","").startswith("executed") and self._pending_action and self._pending_state:
            try:
                # Дополнительный post-action кадр для обучения переходу.
                screenshot=self.device.screenshot_png()
                obs=self.vision.observe(screenshot,now=self.clock())
                after=self.extractor.extract(obs,timestamp=self.clock())
                self.world.learn(self._pending_state,self._pending_action,after)
                # L6: необязательный hook после подтверждённого перехода.
                # В Level5Agent это no-op; L3/L4 логика не меняется.
                try:
                    self.on_verified_transition(self._pending_state,self._pending_action,after)
                except Exception as hook_error:
                    LOG.warning("L6 hook пропущен, L5 продолжает: %s",hook_error)
            except Exception as ex:
                LOG.warning("Пропущено обучение модели мира: %s",ex)
        return result

    def on_verified_transition(self,before,action,after):
        """Точка расширения: старый агент не обязан использовать L6."""
        return None

    def run(self,max_steps=None):
        """Старый step; дополнительная проверка panic между действиями."""
        max_steps=self.cfg.max_steps if max_steps is None else max_steps
        count=0
        while (max_steps==0 or count<max_steps) and not self.panic_event.is_set():
            start=self.clock()
            try:
                result=self.step()
                LOG.info("L5 step=%d %s",count+1,result)
            except KeyboardInterrupt:raise
            except Exception as ex:
                LOG.exception("Остановка на ошибке: %s",ex)
                break
            count+=1
            # event.wait позволяет немедленно прервать межшаговую паузу.
            self.panic_event.wait(max(0,self.cfg.worker_period-(self.clock()-start)))
