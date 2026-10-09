"""Локальная демонстрация конвейера: ничего не устанавливает и не нажимает."""
from .orchestrator import TestOrchestrator,StageEvidence
from .policy import RolloutPolicy

def demo():
    receipts={'unit':StageEvidence(True,{'coverage':.85},'Синтетический пример'),
              'integration':StageEvidence(True,{},'Имитация совместимости'),
              'replay':StageEvidence(True,{},'Локальный повтор')}
    return TestOrchestrator(report_dir='test_reports').run(
        'HumanMimicry','v0.8.0-replay',receipts,category='critical')

if __name__=='__main__':
    print(demo()['verdict'])
