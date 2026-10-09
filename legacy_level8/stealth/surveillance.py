"""Проверка заявленных оператором свойств среды, без сканирования античитов."""
from dataclasses import dataclass

@dataclass(frozen=True)
class EnvironmentReport:
    permitted: bool
    blockers: tuple[str,...]

class CounterSurveillance:
    def evaluate(self, *, online:bool, rooted:bool|None=None,
                 debug_enabled:bool|None=None, proxy_enabled:bool|None=None,
                 vpn_enabled:bool|None=None)->EnvironmentReport:
        reasons=[]
        if online:
            reasons.append('Автоматические игровые действия в онлайн-режиме отключены')
        if rooted is True: reasons.append('Доступ root обнаружен')
        if proxy_enabled is True or vpn_enabled is True:
            reasons.append('Изменения сетевого маршрута требуют проверки оператором')
        if debug_enabled is True:
            reasons.append('Отладка включена: только диагностический сценарий')
        return EnvironmentReport(not reasons,tuple(reasons))
