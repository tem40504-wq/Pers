"""Адаптация стиля общения — не диагностика эмоций и не распознавание личности.

Громкость микрофона и скорость набора — косвенные неоднозначные сигналы;
по умолчанию включены только команды пользователя, обработка голоса opt-in.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class CommunicationStyle:
    name: str
    suggested_verbosity: int
    phrasing: str
    evidence: str


class AffectiveEngine:
    def __init__(self, *, allow_pace=False, allow_voice=False):
        self.allow_pace=allow_pace
        self.allow_voice=allow_voice
        self.stop_events=deque(maxlen=50)
        self.paces=deque(maxlen=20)
        self.voice_levels=deque(maxlen=20)
        self.operator_override: int | None=None

    def record_stop(self, timestamp=None):
        self.stop_events.append(time.monotonic() if timestamp is None else float(timestamp))

    def record_typing(self, characters:int, elapsed_seconds:float):
        if not self.allow_pace:return
        if not 1<=characters<=500 or not .1<=elapsed_seconds<=300:return
        self.paces.append(min(20.0,characters/elapsed_seconds))

    def record_voice_level(self, rms:float):
        if not self.allow_voice:return
        if type(rms) not in (float,int) or not math.isfinite(rms) or not 0<=rms<=1:return
        self.voice_levels.append(float(rms))  # Только RMS, никакой записи аудио.

    def set_operator_verbosity(self,level:int):
        if type(level) is not int or level not in range(4):raise ValueError('Уровень 0..3')
        self.operator_override=level

    def suggest_style(self,now=None) -> CommunicationStyle:
        now=time.monotonic() if now is None else float(now)
        stops=sum(0<=now-t<=120 for t in self.stop_events)
        rapid=bool(self.paces and sum(self.paces)/len(self.paces)>8.5)
        # Это не утверждение об эмоциях оператора.
        busy=stops>=2 or rapid
        if self.operator_override is not None:
            return CommunicationStyle('operator_override',self.operator_override,
                                      'Уровень детализации выбран оператором', 'прямое указание')
        if busy:
            return CommunicationStyle('concise',1,'Кратко: действие, причина, риск. Без экспериментов.',
                                      'частые стопы или высокий темп ввода (не диагноз)')
        return CommunicationStyle('standard',2,'Подробно по запросу; эксперименты только после разрешения.',
                                  'нет признаков необходимости сокращать ответы')

    @staticmethod
    def agent_tone(confidence:float, risk:str='safe') -> str:
        # «Эмоция» — только стилистическая метка, не внутреннее чувство ИИ.
        if risk!='safe' or confidence<.5:return 'осторожность'
        if confidence>=.8:return 'уверенность'
        return 'исследовательский интерес'


class AffectiveOperatorAssistant:
    """Прокси прежнего OperatorAssistant без изменения его безопасных команд."""
    def __init__(self,legacy,engine:AffectiveEngine):
        self.legacy=legacy
        self.engine=engine

    def __getattr__(self,name):
        # Наследуем интерфейс прежнего OperatorAssistant для dashboard.
        return getattr(self.legacy,name)

    def set_verbosity(self,level:int):
        result=self.legacy.set_verbosity(level)
        self.engine.set_operator_verbosity(level)
        return result

    def compact(self):
        payload=self.legacy.compact()
        style=self.engine.suggest_style()
        payload['l6_communication']={'style':style.name,
                                     'suggested_verbosity':style.suggested_verbosity,
                                     'evidence':style.evidence}
        return payload

    def explain_current_state(self):
        return self.legacy.explain_current_state()

    def explain_decision(self,action=None):
        style=self.engine.suggest_style()
        base=self.legacy.explain_decision(action)
        return base.split('. Прогноз:')[0] if style.name=='concise' else base

    def receive_feedback(self,message:str):
        return self.legacy.receive_feedback(message)
