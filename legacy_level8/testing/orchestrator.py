"""Семь последовательных ворот: отсутствие отчёта = провал, не успех."""
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime,timezone
import json
from pathlib import Path
from .policy import RolloutPolicy,STAGES

@dataclass(frozen=True)
class StageEvidence:
    passed:bool
    measurements:dict = field(default_factory=dict)
    description:str=''

class TestOrchestrator:
    def __init__(self,policy:RolloutPolicy|None=None,report_dir='test_reports'):
        self.policy=policy or RolloutPolicy()
        self.report_dir=Path(report_dir);self.report_dir.mkdir(parents=True,exist_ok=True)

    def run(self,module:str,version:str,receipts:dict[str,StageEvidence],*,category=None,operator_approved=False,skipped_stages=()):
        required=self.policy.required(module,category)
        records=[];allowed=True
        skipped_stages=set(skipped_stages)
        if skipped_stages:
            # Пропуск допустим только в лаборатории и никогда не выдаёт PASS.
            allowed=False
        for name in required:
            if name in skipped_stages:
                records.append({'stage':name,'status':'SKIPPED_LAB_ONLY',
                                'reason':'Пропуск увеличивает риск; production запрещён'})
                continue
            ev=receipts.get(name)
            if not ev:
                records.append({'stage':name,'status':'BLOCKED','reason':'Нет подписанного/проверенного результата'})
                allowed=False;break
            m=ev.measurements
            good=ev.passed
            if name=='unit' and (module in self.policy.config.get('critical',[]) or category=='critical' or module in ('HumanMimicry','InputRandomization','SafeMode','SessionSimulator')):
                good=good and float(m.get('coverage',0))>=self.policy.config['minimum_coverage']
            if name=='sandbox':good=good and float(m.get('minutes',0))>=self.policy.config['sandbox_minutes'] and m.get('offline',False)
            if name=='shadow':good=good and float(m.get('minutes',0))>=self.policy.config['shadow_minutes'] and float(m.get('agreement',0))>.80
            if name=='ab':good=good and int(m.get('sessions_each',0))>=self.policy.config['ab_sessions_each'] and bool(m.get('statistically_better',False))
            if name=='production':good=good and operator_approved and bool(m.get('offline_or_authorized_environment',False))
            records.append({'stage':name,'status':'PASS' if good else 'FAIL','metrics':m,'note':ev.description})
            if not good:allowed=False;break
        report={'module':module,'version':version,'at':datetime.now(timezone.utc).isoformat(),
                'required':required,'stages':records,'verdict':'PASS' if allowed else 'LAB_ONLY' if skipped_stages else 'BLOCK',
                'limitations':['Бан аккаунта не может быть предсказан тестами','Успех Shadow не означает разрешение ToS']}
        target=self.report_dir/f'{module}_{version.replace("/","_")}.json'
        target.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        return report
