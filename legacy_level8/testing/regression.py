"""Отслеживание регрессий и возврат на утверждённый снимок."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json,time

@dataclass(frozen=True)
class Regression:
    metric:str
    baseline:float
    current:float
    relative_change:float
    critical:bool

class RegressionTracker:
    # Для этих метрик меньше — лучше; для остальных выше — лучше.
    DIRECTIONS={'win_rate':'higher','damage':'higher','healing':'higher',
                'level_time_s':'lower','battery_drain_pct':'lower','temperature_c':'lower',
                'security_errors':'zero','captcha_count':'zero'}
    def check(self,baseline:dict,current:dict,threshold=.10)->list[Regression]:
        hits=[]
        for key,mode in self.DIRECTIONS.items():
            if key not in baseline or key not in current:continue
            a,b=float(baseline[key]),float(current[key])
            if mode=='zero':
                if b>0:hits.append(Regression(key,a,b,1.,True))
                continue
            if a<=0:continue
            relative=(a-b)/a if mode=='higher' else (b-a)/a
            if relative>threshold:
                hits.append(Regression(key,a,b,relative,True))
        return hits

class AutoRollback:
    def __init__(self,version_manager,stable_version,log_path,emergency=None,replay=None):
        self.versions=version_manager;self.stable=stable_version
        self.log=Path(log_path);self.log.parent.mkdir(parents=True,exist_ok=True)
        self.emergency=emergency;self.replay=replay
    def trigger(self,reason,regressions=(),blackbox_dir=None)->str:
        # В первую очередь останавливаем новые действия.
        if self.emergency:self.emergency.panic()
        if self.replay and blackbox_dir:self.replay.freeze_blackbox(blackbox_dir)
        self.log.open('a',encoding='utf-8').write(json.dumps({
            'ts':time.time(),'reason':reason,
            'regressions':[vars(x) for x in regressions],
            'target':self.stable},ensure_ascii=False)+'\n')
        return self.versions.rollback(self.stable)
