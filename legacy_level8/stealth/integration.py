"""Level 8 как необязательная надстройка, без замены MobileAgent."""
from __future__ import annotations
from pathlib import Path
import time
from mobile_core.agent import MobileAgent
from mobile_core.contracts import Decision
from .detection import AntiCheatDetector
from .safe import SafeMode
from .session import SessionSimulator
from .human import HumanMimicry
from .warnings import WARNING,RiskJournal

class Stage8Agent(MobileAgent):
    def __init__(self,*args,replay=None,version_manager=None,rollback=None,
                 online=True,offline_qa=False,shadow=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.replay=replay;self.version_manager=version_manager;self.rollback=rollback
        self.online=bool(online)
        if offline_qa:
            # Прямой флаг не является подтверждением разрешения.
            self.security.require('level8_offline_qa')
        self.offline_qa=bool(offline_qa)
        self.safe_mode=SafeMode(online=online)
        self.detector=AntiCheatDetector()
        self.session=SessionSimulator()
        self.mimic=HumanMimicry()
        self.shadow=shadow
        self._warning=None;self._pending_incident=None
        self.risk_journal=RiskJournal(self.security.audit)
        self._session_start=time.monotonic()
        self._last_risk_interval=-1

    def enable_offline_qa(self,callback=input):
        # Ни установка ПО, ни выполнение сетевых операций не являются частью этого действия.
        allowed=self.security.request(
            'level8_offline_qa',
            'Тестирование плавности жестов и ограничений в заранее разрешённой офлайн-игре',
            'Выявление ошибок координат, опасных повторов и зависаний до выпуска',
            WARNING + ' Риск случайного касания и изменения прогресса.',
            callback=callback)
        self.offline_qa=bool(allowed)
        return self.offline_qa

    def postprocess_decision(self,obs,decision):
        # Онлайн-режим по умолчанию только наблюдательный.
        signal=self.detector.inspect(obs.texts,obs.scene)
        if signal.detected:
            self._warning=signal.kind
            self.risk_journal.record(signal.kind,details={'scene':obs.scene})
            self.panic()
            if self.security.audit:
                self.security.audit.append('warning',{'reason':signal.kind,'operator_required':True})
            # Чёрный ящик и откат запускаются после записи текущего кадра.
            self._pending_incident=signal.kind
            return Decision('wait','Предупреждение безопасности, требуется оператор')
        if self.offline_qa:
            limits=self.session.check()
            if not limits.allowed:
                return Decision('wait',f'Перерыв: {limits.reason}')
        if self.shadow:
            self.shadow.record(decision.skill_id or decision.kind,None,obs.scene,time.monotonic())
            return Decision('wait','Shadow Mode — только предсказание')
        decision=self.safe_mode.filter(decision,scene=obs.scene,
                                       approved=self.offline_qa)
        return decision

    def on_cycle_complete(self,obs,decision,status,frame):
        # Периодическая отметка о длительности сессии без «оценки вероятности бана».
        elapsed=(time.monotonic()-self._session_start)/60
        slot=int(elapsed//5)
        if slot>self._last_risk_interval:
            self.risk_journal.record('session',elapsed_minutes=round(elapsed,1),
                                     details={'online':self.online,'dry_run':self.dry_run})
            self._last_risk_interval=slot
        # Зафиксируем текущий кадр (если в нём нет приватных данных),
        # после чего оформим инцидент. Команды уже остановлены через panic().
        if self.replay:
            self.replay.append(
                state={'hp':obs.hp,'mp':obs.mp,'scene':obs.scene,'temperature_c':obs.thermal_c},
                action={'kind':decision.kind,'skill':decision.skill_id,'status':status},
                outcome='safety_warning' if self._warning else 'not_evaluated',
                frame_jpeg=frame,private=bool(self._warning))
        incident=self._pending_incident
        if not incident:return
        self._pending_incident=None
        where=None
        if self.replay:
            where=self.replay.root/'incidents'/f'{int(time.time())}_{incident}'
            self.replay.freeze_blackbox(where)
        if self.rollback and self.version_manager and (self.version_manager.active() or '').endswith('-prod'):
            try:self.rollback.trigger(f'safety:{incident}',blackbox_dir=where)
            except (ValueError,OSError) as ex:
                if self.security.audit:self.security.audit.append('rollback_failed',{'error':str(ex)})
