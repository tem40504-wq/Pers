"""Рой мобильного типа: очередь задач + быстрый тактик + редкая проверка ресурсов."""
from __future__ import annotations
import heapq,time,json
from pathlib import Path
from .contracts import Decision,Task,Observation

class TaskQueue:
    def __init__(self):self.q=[]
    def put(self,name,priority=10,**params):heapq.heappush(self.q,Task(priority,time.monotonic(),name,params))
    def next(self):return heapq.heappop(self.q) if self.q else None

class SkillLibrary:
    def __init__(self,path):
        raw=json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(raw,dict):raise ValueError('Навыки должны быть словарём')
        self.skills=raw
    def by_label(self,label):
        for sid,v in self.skills.items():
            if v.get('label')==label and v.get('action') in ('tap','swipe') and v.get('approved',False):return sid,v
        return None,None

class Logistic:
    def check(self,obs:Observation):
        if obs.hp is not None and obs.hp<.25:return {'low_hp':True,'reason':'Низкий HP; требуется известный навык'}
        return {}

class Tactician:
    def __init__(self,skills:SkillLibrary,logistic=None):
        self.skills=skills;self.logistic=logistic or Logistic();self.tasks=TaskQueue();self.current_goal="observe"
    def decide(self,obs:Observation)->Decision:
        task=self.tasks.next()
        if task is not None:self.current_goal=task.name
        check=self.logistic.check(obs)
        if check.get('low_hp'):
            # Не угадываем координаты зелья по низкому HP.
            return Decision('wait','Недостаточно подтверждённых данных для лечения')
        for target in sorted(obs.detections,key=lambda z:-z.confidence):
            sid,skill=self.skills.by_label(target.label)
            if not skill or target.confidence<.85:continue
            x1,y1,x2,y2=target.bbox
            return Decision('tap',f'Проверенная цель: {target.label}',skill_id=sid,
                            x=(x1+x2)//2,y=(y1+y2)//2,confidence=target.confidence)
        return Decision('wait','Ожидание подтверждённого элемента интерфейса')
