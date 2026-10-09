"""Объяснение наблюдаемых фактов, прогнозов и решений; не раскрытие скрытых мыслей VLM.

Все формулировки опираются только на переданное состояние/журнал.
Операторские команды не обходят DSL и существующий ActionExecutor.
"""
from __future__ import annotations
from collections import deque
from threading import RLock, Event
from dataclasses import asdict
import time
import re

from ..models import Action

class OperatorAssistant:
    def __init__(self, verbosity=1, panic_event: Event | None = None):
        self.lock=RLock()
        self.verbosity=1
        self.panic_event=panic_event or Event()
        self.last_state=None
        self.last_prediction=None
        self.last_action=None
        self.last_goal="не определена"
        self.decision_reason=""
        self.lessons=deque(maxlen=30)
        self.tutorial_seen=set()
        self.safety_log=deque(maxlen=100)
        self.feedback=deque(maxlen=100)
        self.no_consumables=False
        self.must_wait=False
        self.set_verbosity(verbosity)

    def set_verbosity(self, level: int):
        if type(level) is not int or level not in range(4):
            raise ValueError("Уровень детализации 0–3")
        with self.lock:
            self.verbosity=level
        return level

    def observe(self, state, prediction=None, action=None, goal=None, explanation=""):
        with self.lock:
            self.last_state=state
            self.last_prediction=prediction
            if action is not None: self.last_action=action
            if goal is not None: self.last_goal=str(goal)
            self.decision_reason=str(explanation)[:500]

    @staticmethod
    def _percent(x):
        return "не определено" if x is None else f"{round(100*x)}%"

    def explain_current_state(self) -> str:
        with self.lock:
            s=self.last_state
            if s is None:
                return "Данных об игре пока нет."
            text=f"HP {self._percent(s.hp)}, MP {self._percent(s.mp)}; цель — {self.last_goal}."
            if self.verbosity >= 2 and self.last_prediction:
                p=self.last_prediction
                text+=f" Прогноз HP через {p.horizon:.1f} с: {self._percent(p.hp)}, оценка надёжности {p.confidence:.2f}."
            if self.verbosity >= 3:
                text+=f" Кулдауны: {s.cooldowns}; дистанция: {s.distance}; источник: GameStateVector."
            return text

    def explain_decision(self, action: Action | None = None) -> str:
        with self.lock:
            a=action or self.last_action
            if a is None:
                return "Решение пока не принято."
            text=f"Действие: {a.kind}."
            if self.verbosity>=1:
                text+=f" Причина: {a.reason or self.decision_reason or 'нет подтверждённых данных'}."
            if self.verbosity>=2 and self.last_prediction:
                p=self.last_prediction
                text+=f" Прогноз: {', '.join(p.events) if p.events else 'событий нет'}; уверенность {p.confidence:.2f}."
            if self.verbosity>=3:
                text+=f" Риск: {a.risk}; confidence: {a.confidence:.2f}; {self.decision_reason}"
            return text

    def answer_operator_question(self, question: str) -> str:
        q=question.lower().strip()[:300]
        with self.lock:
            if any(k in q for k in ("ульт", "супер", "ultimate")):
                if self.last_state is None:
                    return "Нет текущих данных об ультимативной способности."
                cds=self.last_state.cooldowns
                if "ultimate" in cds:
                    return f"Наблюдаемый кулдаун ульты: {cds['ultimate']:.1f} сек. Возможность применить навык отдельно проверяет Skill Library."
                return "Кулдаун ульты не распознан; автоматическое применение без подтверждённого навыка запрещено."
            if "почему" in q or "зачем" in q:
                return self.explain_decision()
            if "что" in q or "состояни" in q:
                return self.explain_current_state()
            if "безопас" in q or "разрешен" in q:
                return "Все реальные нажатия проходят существующий ActionExecutor; установка пакетов — только через PermissionGate."
            return "Недостаточно данных для уверенного ответа. Уточни: «Почему это действие?» или «Какое состояние?»."

    def generate_tutorial(self, mechanic: str, evidence_count: int = 0, source: str = ""):
        """Публикуем подсказку только после нескольких подтверждённых наблюдений."""
        if evidence_count < 3 or not source:
            return None
        key=mechanic.strip().lower()
        with self.lock:
            if key in self.tutorial_seen or not key:
                return None
            self.tutorial_seen.add(key)
            message=f"Возможная механика: {mechanic}. Подтверждений: {evidence_count}; источник: {source}. Проверь перед применением."
            self.lessons.append(message)
            return message

    def receive_feedback(self, message: str) -> str:
        """Простая намеренно ограниченная обработка текстовых команд оператора."""
        q=message.lower().strip()[:200]
        with self.lock:
            level_match=re.search(r"(?:verbosity|детализаци[яиюи]|уровень)\s*[:=]?\s*([0-3])\b",q)
            if level_match:
                self.verbosity=int(level_match.group(1))
                result=f"Уровень пояснений переключён на {self.verbosity}."
            elif any(x in q for x in ("panic", "аварийн", "стоп", "останов")):
                self.panic_event.set()
                result="Аварийная остановка запрошена. Новые действия заблокированы."
            elif "не пей" in q or "без зель" in q:
                self.no_consumables=True
                self.must_wait=True
                result="Применение предметов заблокировано. Агент будет ожидать, пока оператор не подтвердит безопасный способ отхода."
            elif "беги" in q or "отступ" in q:
                self.must_wait=True
                result="Запрошено отступление. Без проверенного навыка движения агент ждёт; не делает случайных свайпов."
            elif "продолж" in q or "снять огранич" in q:
                if self.panic_event.is_set():
                    result="PANIC STOP активен. Для возобновления требуется новый запуск и проверка оператора."
                else:
                    self.must_wait=False
                    result="Ожидание снято; постоянный запрет на предметы сохраняется, пока оператор не снимет его отдельно."
            elif "разреши зель" in q:
                self.no_consumables=False
                result="Запрет на предметы снят; старый Safety Gate продолжает проверку."
            else:
                result="Команда не распознана. Никаких действий не выполнено."
            self.feedback.append({"at":time.time(),"message":message[:200],"result":result})
            return result

    def safe_override(self, action: Action) -> Action:
        with self.lock:
            if self.panic_event.is_set():
                return Action(reason="PANIC STOP")
            if self.must_wait:
                return Action(reason="Оператор запросил безопасное ожидание")
            if self.no_consumables and ("potion" in action.reason.lower() or
                (action.target and "potion" in action.target.label.lower()) or
                "зель" in action.reason.lower()):
                return Action(reason="Оператор запретил использовать предметы")
            return action

    def compact(self):
        with self.lock:
            return {"verbosity":self.verbosity,"state":self.explain_current_state(),
                    "decision":self.explain_decision(),"panic":self.panic_event.is_set(),
                    "last_goal":self.last_goal,"feedback":list(self.feedback)[-5:],
                    "lessons":list(self.lessons)[-5:],"safety":list(self.safety_log)[-15:]}
