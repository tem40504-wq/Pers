"""Принудительный режим только наблюдения для онлайн-игр."""
from __future__ import annotations
from dataclasses import replace
import time
from mobile_core.contracts import Decision

class SafeMode:
    def __init__(self, *, online=True, max_actions_per_sec=3.):
        self.online=bool(online)
        self.max_actions_per_sec=min(float(max_actions_per_sec),5.)
        self._last_action=-1e20
    def filter(self,decision:Decision,*,now=None,scene='unknown',approved=False)->Decision:
        # Онлайн — только наблюдение: никакой «скрытности» или обхода ToS.
        if self.online:
            return Decision('wait','Онлайн: SafeMode допускает только наблюдение')
        if decision.kind=='wait':return decision
        if not approved:
            return Decision('wait','Нет подтверждения офлайн-тестирования')
        if any(tag in scene.lower() for tag in ('pvp','ranked','purchase','shop')):
            return Decision('wait','Небезопасная игровая сцена')
        now=time.monotonic() if now is None else now
        if now-self._last_action < 1/self.max_actions_per_sec:
            return Decision('wait','Ограничение частоты действий')
        self._last_action=now
        return decision
