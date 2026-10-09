"""OperatorAssistant-lite, доступный и без тяжёлого VLM."""
from .contracts import Observation,Decision

class OperatorAssistant:
    def __init__(self,verbosity:int=1):self.verbosity=max(0,min(3,verbosity))
    def explain_current_state(self,obs:Observation)->str:
        if self.verbosity==0:return ''
        parts=[f'Сцена: {obs.scene}']
        if obs.hp is not None:parts.append(f'HP: {obs.hp:.0%}')
        if obs.mp is not None:parts.append(f'MP: {obs.mp:.0%}')
        if self.verbosity>=2:parts.append(f'Объектов: {len(obs.detections)}; OCR: {len(obs.texts)}')
        return '; '.join(parts)
    def explain_decision(self,d:Decision)->str:
        if self.verbosity==0:return d.kind
        return f'{d.kind}: {d.reason}' + (f'; confidence={d.confidence:.2f}' if self.verbosity>=2 else '')
