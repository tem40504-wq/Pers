"""Консервативные политики: critical нельзя выпускать без всех ворот.

policy.yaml хранит JSON-совместимый YAML для чтения без PyYAML.
"""
from __future__ import annotations
import json
from pathlib import Path

STAGES=('unit','integration','replay','sandbox','shadow','ab','production')
CRITICAL={'HumanMimicry','InputRandomization','SafeMode','SessionSimulator'}
SECONDARY={'Logging','Dashboard'}

class RolloutPolicy:
    def __init__(self,config=None):
        self.config=config or {
            'critical':list(STAGES),
            'secondary':['unit','integration'],
            'experimental':list(STAGES),
            'default':list(STAGES),
            'minimum_coverage':.80,
            'sandbox_minutes':15,
            'shadow_minutes':60,
            'ab_sessions_each':30}
    @classmethod
    def load(cls,path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))
    def required(self,module,category=None):
        category=category or ('critical' if module in CRITICAL else 'secondary' if module in SECONDARY else 'experimental')
        return list(self.config.get(category,self.config['default']))
    def authorize_skip(self,module,stage,*,operator_approved=False):
        if not operator_approved:raise PermissionError('Оператор не подтвердил пропуск')
        if module in CRITICAL:raise PermissionError('Критические ворота нельзя обходить для production')
        return {'module':module,'stage':stage,'warning':'Пропуск снижает достоверность тестов; production запрещён'}
