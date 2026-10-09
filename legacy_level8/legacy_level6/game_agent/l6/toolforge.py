"""ToolForge: генерирует и тестирует ограниченный ПОДНАБОР Python без exec/eval.

Это интерпретатор AST, а не полноценная системная песочница. Он НЕ выполняет
произвольный Python. Для внешнего кода используйте отдельный контейнер с
системной изоляцией, отключённой сетью и разрешением владельца.
"""
from __future__ import annotations
from dataclasses import dataclass
import ast
import math
import operator
import time


class UnsafeTool(ValueError): pass


OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,
     ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,
     ast.Mod:operator.mod}
CMPS={ast.Eq:operator.eq,ast.NotEq:operator.ne,ast.Lt:operator.lt,
      ast.LtE:operator.le,ast.Gt:operator.gt,ast.GtE:operator.ge}
BUILTINS={'min':min,'max':max,'abs':abs,'round':round}


class SafePythonSubset:
    """Принимает только `def tool(inputs)` без import/атрибутов/циклов.

    Модель может предложить текст, но никогда не получит доступ к ОС,
    файлам, сети, Python builtins, модульным импортам или состоянию агента.
    """
    def __init__(self, code:str):
        if not isinstance(code,str) or len(code)>6000:
            raise UnsafeTool('Исходник слишком большой')
        tree=ast.parse(code,mode='exec')
        if len(tree.body)!=1 or type(tree.body[0]) is not ast.FunctionDef:
            raise UnsafeTool('Разрешена только функция tool(inputs)')
        fn=tree.body[0]
        if fn.name!='tool' or len(fn.args.args)!=1 or fn.args.args[0].arg!='inputs' or fn.decorator_list or fn.args.defaults or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg:
            raise UnsafeTool('Сигнатура строго def tool(inputs)')
        if len(list(ast.walk(tree)))>120:
            raise UnsafeTool('Сложность превышена')
        allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Assign,
                 ast.Return,ast.If,ast.Name,ast.Load,ast.Store,ast.Constant,
                 ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.Call,
                 ast.Subscript,ast.List,ast.Tuple,ast.Dict,
                 ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,
                 ast.UAdd,ast.USub,ast.Not,ast.And,ast.Or,
                 ast.Eq,ast.NotEq,ast.Gt,ast.GtE,ast.Lt,ast.LtE)
        for node in ast.walk(tree):
            if not isinstance(node,allowed):
                raise UnsafeTool(f'Запрещённый узел AST: {type(node).__name__}')
            if isinstance(node,ast.Name) and (node.id.startswith('_') or
                   (isinstance(node.ctx,ast.Load) and node.id in ('open','exec','eval','globals','locals'))):
                raise UnsafeTool('Недопустимое имя')
            if isinstance(node,ast.Call) and (type(node.func) is not ast.Name or
               node.func.id not in BUILTINS or node.keywords):
                raise UnsafeTool('Разрешены только min/max/abs/round')
            if isinstance(node,ast.Constant) and (type(node.value) not in (int,float,str,bool,type(None)) or
               (isinstance(node.value,str) and len(node.value)>128)):
                raise UnsafeTool('Недопустимая константа')
            if isinstance(node,ast.Assign) and (len(node.targets)!=1 or type(node.targets[0]) is not ast.Name or
              node.targets[0].id in ('inputs',*BUILTINS)):
                raise UnsafeTool('Недопустимое присваивание')
        self.fn=fn

    @staticmethod
    def _value(value, depth=0):
        # Ограничиваем вычисления, вложенность и размер ВСЕХ объектов.
        if depth>3: raise UnsafeTool('Слишком глубокий объект')
        if isinstance(value,(int,float)) and (not math.isfinite(value) or abs(value)>1e9):
            raise UnsafeTool('Выход за пределы арифметики')
        if isinstance(value,(list,tuple,dict,str)) and len(value)>100:
            raise UnsafeTool('Слишком большой результат')
        if isinstance(value,dict):
            for k,v in value.items():
                if type(k) not in (str,int) or len(str(k))>60:
                    raise UnsafeTool('Недопустимый ключ')
                SafePythonSubset._value(v,depth+1)
        if isinstance(value,(list,tuple)):
            for v in value:SafePythonSubset._value(v,depth+1)
        if isinstance(value,(dict,list,tuple,str,int,float,bool,type(None))):
            return value
        raise UnsafeTool('Недопустимый тип')

    def run(self, inputs:dict, *, max_operations=400, max_seconds=.05):
        if not isinstance(inputs,dict) or len(inputs)>30 or any(type(k) is not str or len(k)>40 for k in inputs):
            raise UnsafeTool('Некорректные входы')
        for v in inputs.values(): self._value(v)
        env={'inputs':dict(inputs)}
        end=time.monotonic()+max_seconds
        budget=[max_operations]
        def evaluate(node):
            budget[0]-=1
            if budget[0]<0 or time.monotonic()>end:raise UnsafeTool('Превышен бюджет исполнения')
            if isinstance(node,ast.Constant):return node.value
            if isinstance(node,ast.Name):
                if node.id not in env: raise UnsafeTool('Неизвестная переменная')
                return env[node.id]
            if isinstance(node,ast.Subscript):
                obj=evaluate(node.value); key=evaluate(node.slice)
                if type(obj) not in (dict,list,tuple) or type(key) not in (str,int):
                    raise UnsafeTool('Недопустимая индексация')
                if type(obj) in (list,tuple) and (type(key) is not int or abs(key)>100):
                    raise UnsafeTool('Индекс за пределами')
                try:return obj[key]
                except (IndexError,KeyError) as ex: raise UnsafeTool('Отсутствует ключ') from ex
            if isinstance(node,(ast.List,ast.Tuple)):
                items=[evaluate(i) for i in node.elts]
                return self._value(items if isinstance(node,ast.List) else tuple(items))
            if isinstance(node,ast.Dict):
                result={evaluate(k):evaluate(v) for k,v in zip(node.keys,node.values)}
                return self._value(result)
            if isinstance(node,ast.UnaryOp):
                x=evaluate(node.operand)
                if type(node.op) is ast.Not:return not x
                if type(x) not in (int,float):raise UnsafeTool('Ожидается число')
                return self._value(x if type(node.op) is ast.UAdd else -x)
            if isinstance(node,ast.BinOp):
                x,y=evaluate(node.left),evaluate(node.right)
                if type(x) not in (int,float) or type(y) not in (int,float):raise UnsafeTool('Только числовые операции')
                if type(node.op) not in OPS:raise UnsafeTool('Оператор запрещён')
                try:return self._value(OPS[type(node.op)](x,y))
                except (OverflowError,ZeroDivisionError) as ex:raise UnsafeTool('Ошибка арифметики') from ex
            if isinstance(node,ast.Compare):
                left=evaluate(node.left)
                for op,part in zip(node.ops,node.comparators):
                    right=evaluate(part)
                    if type(op) not in CMPS:raise UnsafeTool('Сравнение запрещено')
                    if not CMPS[type(op)](left,right):return False
                    left=right
                return True
            if isinstance(node,ast.BoolOp):
                if type(node.op) is ast.And:
                    return all(evaluate(v) for v in node.values)
                if type(node.op) is ast.Or:
                    return any(evaluate(v) for v in node.values)
                raise UnsafeTool('Неверная логическая операция')
            if isinstance(node,ast.Call):
                args=[evaluate(x) for x in node.args]
                return self._value(BUILTINS[node.func.id](*args))
            raise UnsafeTool('Неизвестное выражение')
        def block(statements):
            for stmt in statements:
                if isinstance(stmt,ast.Assign):
                    env[stmt.targets[0].id]=self._value(evaluate(stmt.value))
                elif isinstance(stmt,ast.Return):return True,self._value(evaluate(stmt.value))
                elif isinstance(stmt,ast.If):
                    done,value=block(stmt.body if evaluate(stmt.test) else stmt.orelse)
                    if done:return True,value
                else:raise UnsafeTool('Недопустимая команда')
            return False,None
        done,result=block(self.fn.body)
        if not done:raise UnsafeTool('Отсутствует return')
        return result


@dataclass(frozen=True)
class ToolTest:
    inputs:dict
    expected:object


class ToolForge:
    """Проверка, тестирование и регистрация ТОЛЬКО чистого вычисления.

    Нельзя превращать результат генерируемого инструмента непосредственно
    в клик или команду устройства; DSL и Safety Gate остаются обязательными.
    """
    def __init__(self, permission_gate=None):
        self.gate=permission_gate
        self.staged={}
        self.active={}

    def synthesize(self, name: str, specification: str, generator, tests: list[ToolTest]):
        """VLM возвращает ИСХОДНИК, но не исполняется. Дальше только AST-аудит."""
        if len(specification)>1000:
            raise ValueError('Спецификация слишком длинная')
        source = generator(specification)
        if not isinstance(source,str):
            raise UnsafeTool('Генератор не вернул текст исходника')
        return self.propose(name,source,tests)

    def propose(self, name:str, source:str, tests:list[ToolTest]):
        import re
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',name) or len(tests)<1 or len(tests)>20:
            raise ValueError('Неверное имя или количество тестов')
        safe=SafePythonSubset(source)
        for test in tests:
            result=safe.run(test.inputs)
            if result!=test.expected:raise ValueError(f'Тест не прошёл: {test.inputs}')
        self.staged[name]={'source':source,'engine':safe,'tests':len(tests)}
        return {'name':name,'tests_passed':len(tests),'requires_approval':True}

    def activate(self,name:str):
        if name not in self.staged:raise KeyError(name)
        if self.gate is None: raise PermissionError('Нет PermissionGate')
        item=self.staged[name]
        if not self.gate.require_external_action(
            title=f'Добавить вычислительный навык {name}',
            exact_action=f'Активировать ограниченную AST-функцию {name} в локальном ToolCatalog',
            technical_reason='Агенту не хватает вычисления для планирования; все тесты пройдены',
            user_benefit='Расширяется набор безопасных вычислений без установки библиотек',
            risks='Возможны ошибочные результаты на нетестированных входах; сетевых/системных прав нет'):
            return False
        self.active[name]=item['engine']
        return True

    def call(self,name:str,inputs:dict):
        if name not in self.active:raise PermissionError('Инструмент не утверждён')
        return self.active[name].run(inputs)
