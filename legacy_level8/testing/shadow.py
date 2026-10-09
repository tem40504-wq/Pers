"""Shadow Mode: прогнозы БЕЗ отправки жестов, сравнение с действиями оператора."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ShadowReport:
    comparisons: int
    agreement: float
    eligible: bool

class ShadowMode:
    def __init__(self,min_samples=100,threshold=.80,min_hours=1.):
        self.min_samples=min_samples;self.threshold=threshold;self.min_hours=min_hours
        self.records=[]
    def record(self,predicted:str,actual_operator_action:str|None,scene_id:str,ts:float):
        # Не переносим действия в Android Controller.
        self.records.append({'predicted':predicted,'actual':actual_operator_action,
                             'scene':scene_id,'ts':ts})
    def report(self)->ShadowReport:
        paired=[r for r in self.records if r['actual'] is not None]
        n=len(paired)
        agreement=sum(r['predicted']==r['actual'] for r in paired)/n if n else 0.
        span=(max(r['ts'] for r in paired)-min(r['ts'] for r in paired))/3600 if n>=2 else 0.
        return ShadowReport(n,agreement,n>=self.min_samples and span>=self.min_hours and agreement>=self.threshold)
