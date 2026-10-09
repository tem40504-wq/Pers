"""Level6Agent наследует Level5Agent и сохраняет весь Safety/DSL/Swarm pipeline."""
from __future__ import annotations
from dataclasses import asdict
import logging

from ..l5.agent_l5 import Level5Agent
from .continual import ContinualLearner, Experience
from .physics import PhysicsWorldModel
from .affective import AffectiveEngine, AffectiveOperatorAssistant

LOG=logging.getLogger(__name__)


class Level6Agent(Level5Agent):
    def __init__(self,cfg,*,profiles_dir='data/l6_profiles',**kwargs):
        super().__init__(cfg,**kwargs)
        try:
            self.learner=ContinualLearner(directory=profiles_dir)
            self.learner.select_game(cfg.game_id)
        except (OSError,ValueError,TypeError) as exc:
            LOG.warning('L6 profiles временно недоступны, L5 fallback: %s',exc)
            self.learner=None
        self.physics=PhysicsWorldModel(base_world_model=self.world)
        self.affective=AffectiveEngine()
        self.operator_explainer=AffectiveOperatorAssistant(self.operator,self.affective)
        # Дашборд использует прокси только для ОБЪЯСНЕНИЙ и выбора уровня.
        # Команды пользователя и флаг STOP делегируются старому оператору.
        self.dashboard.operator=self.operator_explainer
        # FederatedHub и ToolForge НЕ создают сетевые соединения/код в цикле.
        self._transition_count=0

    @staticmethod
    def _safe_state(state):
        # Числовые данные без скриншотов, текстов, аккаунтов и токенов.
        return {key:getattr(state,key) for key in ('hp','mp','distance','threat')}

    def on_verified_transition(self,before,action,after):
        # Существующий L5.learn уже выполнен; добавляем только replay.
        if self.learner is None:return
        reward=( (after.hp-before.hp) if before.hp is not None and after.hp is not None else 0.0)
        if before.threat is not None and after.threat is not None:
            reward+=.5*(before.threat-after.threat)
        label=action.target.label if action.target else action.kind
        self.learner.record(Experience(self._safe_state(before),str(label),
                                       float(reward),self._safe_state(after)))
        self._transition_count+=1
        if self._transition_count%25==0:
            self.learner.save()

    def choose_action(self,obs,now):
        # Решение и все ограничения остаются у L5. AffectiveEngine меняет
        # только отображение объяснения и НЕ воздействует на координаты.
        goal,action=super().choose_action(obs,now)
        if self.operator.verbosity:
            LOG.info('L6 explanation: %s',self.operator_explainer.explain_decision(action))
        return goal,action

    def extra_event(self,obs,action,status):
        row=super().extra_event(obs,action,status)
        row['l6']={'game_profile':self.learner.game_id if self.learner else 'unavailable',
                   'experience_count':len(self.learner.replay) if self.learner else 0,
                   'communication_style':self.affective.suggest_style().name,
                   'federation_enabled':False, 'generated_code_execution':False}
        return row

    def run(self,max_steps=None):
        try:
            return super().run(max_steps)
        finally:
            if self.panic_event.is_set():
                self.affective.record_stop()
            self.shutdown()

    def shutdown(self):
        if self.learner:
            try:self.learner.save()
            except OSError as ex:LOG.warning('Не удалось сохранить replay: %s',ex)
