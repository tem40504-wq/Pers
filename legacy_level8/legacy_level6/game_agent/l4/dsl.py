"""Компактный DSL: допускает только IF <логическое условие> THEN <разрешённый навык>.
Никаких eval/exec, импортов, циклов, произвольных ADB-команд или кликов.
"""
from __future__ import annotations
import ast
import re
from typing import Any, Callable, Mapping
from ..models import Action, Observation

_ALLOWED_FACTS = frozenset({
    "hp", "mp", "distance", "predicted_hp", "predicted_mp",
    "predicted_distance", "threat", "predicted_threat", "enemy_mage",
    "danger", "game_over"
})
_EXPR = re.compile(r"^\s*IF\s+(.+?)\s+THEN\s+([a-z_][a-z_0-9]*)\s*\((.*?)\)\s*$", re.I | re.S)
_PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")

class DSLParseError(ValueError):
    pass

class SkillRegistry:
    """Связывает логический навык с уже существующей библиотекой навыков.
    Реализации регистрируются только из локального доверенного кода игры.
    """
    def __init__(self):
        self._skills: dict[str, Callable[[str | None, Observation], Action]] = {}

    def register(self, name: str, handler: Callable[[str | None, Observation], Action]):
        if not re.fullmatch(r"[a-z_][a-z_0-9]*", name):
            raise ValueError("Некорректное имя навыка")
        if not callable(handler):
            raise TypeError("Навык должен быть функцией")
        self._skills[name] = handler

    def invoke(self, name: str, arg: str | None, obs: Observation) -> Action:
        if name not in self._skills:
            return Action(reason=f"Навык {name} не зарегистрирован")
        action = self._skills[name](arg, obs)
        if not isinstance(action, Action):
            raise TypeError("Навык должен вернуть game_agent.models.Action")
        # Старый Safety Gate будет применён позже без обхода.
        return action


class DSLInterpreter:
    def __init__(self, skills: SkillRegistry):
        self.skills = skills

    def _value(self, node: ast.AST, facts: Mapping[str, Any]):
        if isinstance(node, ast.Name) and node.id in _ALLOWED_FACTS:
            return facts.get(node.id)
        if isinstance(node, ast.Constant) and type(node.value) in (bool, int, float, str):
            return node.value
        raise DSLParseError("Неизвестный идентификатор или значение")

    def _condition(self, node: ast.AST, facts: Mapping[str, Any]) -> bool:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            return all(self._condition(n, facts) for n in node.values)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return any(self._condition(n, facts) for n in node.values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._condition(node.operand, facts)
        if isinstance(node, ast.Name):
            return self._value(node, facts) is True
        if isinstance(node, ast.Constant) and type(node.value) is bool:
            return node.value
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left = self._value(node.left, facts)
            right = self._value(node.comparators[0], facts)
            # Неизвестные показатели не считаем равными нулю.
            if left is None or right is None:
                return False
            op = node.ops[0]
            comparisons = {ast.Lt: lambda a,b: a < b, ast.LtE: lambda a,b: a <= b,
                           ast.Gt: lambda a,b: a > b, ast.GtE: lambda a,b: a >= b,
                           ast.Eq: lambda a,b: a == b, ast.NotEq: lambda a,b: a != b}
            for op_type, func in comparisons.items():
                if isinstance(op, op_type):
                    if type(left) is bool or type(right) is bool:
                        if op_type not in (ast.Eq, ast.NotEq):
                            raise DSLParseError("Недопустимое сравнение булевых значений")
                    if type(left) not in (bool, int, float, str) or type(right) not in (bool, int, float, str):
                        return False
                    try:
                        return bool(func(left, right))
                    except TypeError:
                        return False
        raise DSLParseError("Допустимы только сравнения, AND, OR, NOT и скобки")

    @staticmethod
    def _arg(raw: str) -> str | None:
        if not raw.strip():
            return None
        try:
            value = ast.literal_eval(raw.strip())
        except (ValueError, SyntaxError, TypeError) as ex:
            raise DSLParseError("Аргумент навыка — только строка в кавычках") from ex
        if not isinstance(value, str) or len(value) > 80:
            raise DSLParseError("Аргумент должен быть строкой до 80 символов")
        return value

    @staticmethod
    def _validate_ast(tree: ast.AST):
        """Проверяем ВСЁ дерево до вычисления: никакие вызовы не скрыть в OR."""
        ok = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
              ast.Name, ast.Load, ast.Constant, ast.Compare, ast.Lt, ast.LtE,
              ast.Gt, ast.GtE, ast.Eq, ast.NotEq)
        for node in ast.walk(tree):
            if not isinstance(node, ok):
                raise DSLParseError("Недопустимая синтаксическая конструкция")
            if isinstance(node, ast.Name) and node.id not in _ALLOWED_FACTS:
                raise DSLParseError("Неизвестная переменная состояния")
            if isinstance(node, ast.Constant) and type(node.value) not in (bool, int, float, str):
                raise DSLParseError("Недопустимая константа")

    def interpret(self, source: str, facts: Mapping[str, Any], obs: Observation) -> Action:
        if not isinstance(source, str) or len(source) > 800:
            raise DSLParseError("DSL слишком длинный или некорректный")
        m = _EXPR.fullmatch(source)
        if not m:
            raise DSLParseError("Ожидается IF <условие> THEN <навык>(<аргумент>)")
        condition, skill, raw_arg = m.groups()
        if skill.startswith("_") or "__" in skill:
            raise DSLParseError("Недопустимое имя навыка")
        # Преобразование 20% -> 0.20. Только проценты от 0 до 100.
        def to_ratio(match):
            value = float(match[1])
            if value < 0 or value > 100:
                raise DSLParseError("Проценты вне 0–100")
            return str(value / 100.0)
        condition = _PERCENT.sub(to_ratio, condition)
        # Нормализуем операторы в Python AST, но НЕ выполняем сгенерированный код.
        condition = re.sub(r"\bAND\b", "and", condition, flags=re.I)
        condition = re.sub(r"\bOR\b", "or", condition, flags=re.I)
        condition = re.sub(r"\bNOT\b", "not", condition, flags=re.I)
        try:
            tree = ast.parse(condition, mode="eval")
        except SyntaxError as ex:
            raise DSLParseError("Неправильное условие DSL") from ex
        self._validate_ast(tree)
        if not self._condition(tree.body, facts):
            return Action(reason="Условие DSL не выполнено или данные неизвестны")
        return self.skills.invoke(skill.lower(), self._arg(raw_arg), obs)
