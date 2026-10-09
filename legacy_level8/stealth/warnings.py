"""Прозрачные предупреждения и журнал рисков, без оценки вероятности бана."""
from __future__ import annotations
from datetime import datetime,timezone

WARNING=(
    'ВНИМАНИЕ! Автоматизация онлайн-игры может нарушать правила игры. '
    'Возможные последствия: блокировка аккаунта, устройства, потеря прогресса. '
    'Вариативность ввода не делает действия невидимыми. '
    'Level 8 разрешает активные тесты только в согласованной офлайн-среде.'
)

class RiskJournal:
    def __init__(self,audit_logger=None):
        self.audit=audit_logger;self.entries=[]
    def record(self,kind,elapsed_minutes=0,details=None):
        # Категория риска не является вероятностью блокировки.
        duration=float(elapsed_minutes)
        level='elevated' if duration>=90 else 'caution' if duration>=45 else 'baseline'
        entry={'time':datetime.now(timezone.utc).isoformat(),'event':str(kind),
               'minutes':duration,'risk_level':level,'details':details or {}}
        self.entries.append(entry)
        if self.audit:self.audit.append('risk',entry)
        return entry
