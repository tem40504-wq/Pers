"""Явное одноразовое разрешение для действий, изменяющих окружение.

Без `Y` не выполняются ни pip install, ни скачивание весов, ни HID-подключение.
Этот модуль НЕ является изоляцией недоверенных Python-плагинов; плагины
исполняются в том же процессе и должны предварительно проверяться человеком.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import importlib.util
import re
import subprocess
import sys
from typing import Callable


class PermissionDenied(RuntimeError):
    """Пользователь отказал или консоль недоступна."""


class SetupFailed(RuntimeError):
    """Одобренная операция завершилась с ошибкой."""


class Risk(str, Enum):
    LOW = "низкий"
    MEDIUM = "средний"
    HIGH = "высокий"


@dataclass(frozen=True)
class PermissionRequest:
    title: str
    exact_action: str
    technical_reason: str
    user_benefit: str
    risks: str
    risk: Risk = Risk.MEDIUM


@dataclass(frozen=True)
class Dependency:
    module: str
    requirement: str
    purpose: str
    benefit: str
    risks: str


# Белый список создаёт разработчик, но НЕ модель/VLM и НЕ пользовательский DSL.
# pip может загрузить транзитивные зависимости: это сообщается до согласия.
DEPENDENCIES: dict[str, Dependency] = {
    "numpy": Dependency("numpy", "numpy>=1.26,<3", "численные векторы и прогноз", "возможность строить прогноз HP/MP", "загрузка пакета и его зависимостей; место на диске"),
    "cv2": Dependency("cv2", "opencv-python>=4.8,<5", "обработка изображений экрана", "локальное распознавание интерфейса", "установка бинарной библиотеки, использование диска"),
    "PIL": Dependency("PIL", "Pillow>=10,<13", "чтение и изменение изображений", "подготовка скриншотов для анализа", "загрузка стороннего пакета и зависимостей"),
    "requests": Dependency("requests", "requests>=2.31,<3", "HTTP-вызов настроенного сервера VLM", "доступ к локальной либо выбранной облачной модели", "сетевая передача при явном обращении к API"),
    "easyocr": Dependency("easyocr", "easyocr>=1.7,<2", "распознавание текста интерфейса", "чтение заданий и меню", "большие зависимости; OCR может дополнительно скачать веса при первом запуске"),
    "ultralytics": Dependency("ultralytics", "ultralytics>=8.2,<9", "детекция объектов обученной моделью YOLO", "быстрое распознавание известных элементов", "дополнительные зависимости и нагрузка на GPU"),
    "chromadb": Dependency("chromadb", "chromadb>=1,<2", "сохранение семантической памяти", "поиск похожих предыдущих игровых ситуаций", "дисковое хранилище; зависимости могут быть объёмными"),
    "onnxruntime": Dependency("onnxruntime", "onnxruntime>=1.18,<2", "инференс подготовленной ONNX-модели", "локальные предсказания без облачного API", "нагрузка CPU/GPU; внешняя модель требует отдельной проверки"),
    "fastapi": Dependency("fastapi", "fastapi>=0.110,<1", "локальный API для панели оператора", "понимание и остановка агента через браузер", "локальная служба на ПК; сторонние пакеты и дисковое пространство"),
    "uvicorn": Dependency("uvicorn", "uvicorn>=0.29,<1", "локальный веб-сервер", "обновление панели в браузере", "открывается локальный TCP порт; не публикуйте наружу"),
    "sounddevice": Dependency("sounddevice", "sounddevice>=0.4.6,<1", "поток разрешённого аудиоустройства ПК", "обнаружение звуковых подсказок игры", "возможна запись микрофона; выбор устройства обязателен"),
    "tflite_runtime": Dependency("tflite_runtime", "tflite-runtime>=2.14,<3", "инференс локальной аудиомодели", "анализ событий без сетевого API", "есть не на всех версиях Windows; требуется локальная совместимая модель"),
    "torch": Dependency("torch", "torch>=2,<3", "экспериментальное офлайн обучение модели жестов", "UX-эксперименты на добровольных записях", "большой объём загрузки, нагрузка на GPU и CPU"),
    "serial": Dependency("serial", "pyserial>=3.5,<4", "Serial-связь с тестовым HID-устройством", "альтернативное управление на совместимом стенде", "доступ к аппаратному порту; неверная калибровка приводит к неправильному вводу"),
}


class PermissionGate:
    """Показывает четыре обязательных пункта и принимает ТОЛЬКО явное Y.

    Каждое разрешение одноразовое; при ошибках или EOF выбор — N.
    Важно: системные настройки и установку EXE мы никогда не меняем автоматически.
    """
    def __init__(self, ask: Callable[[str], str] = input,
                 output: Callable[[str], object] = print,
                 runner: Callable = subprocess.run):
        self.ask, self.output, self.runner = ask, output, runner

    def approve(self, request: PermissionRequest) -> bool:
        self.output("\n" + "=" * 60)
        self.output("ОФИЦИАЛЬНЫЙ ЗАПРОС РАЗРЕШЕНИЯ — Universal Game Agent")
        self.output(f"Действие: {request.title}")
        self.output(f"Точная операция: {request.exact_action}")
        self.output(f"Техническая причина: {request.technical_reason}")
        self.output(f"Польза: {request.user_benefit}")
        self.output(f"Риски: {request.risks}")
        self.output(f"Уровень риска: {request.risk.value}")
        self.output("Без подтверждения действие НЕ выполнится. Y — разрешить ОДИН раз, N — отказаться.")
        try:
            answer = self.ask("Подтвердить действие? [Y/N]: ")
        except (KeyboardInterrupt, EOFError, OSError):
            answer = "N"
        allowed = isinstance(answer, str) and answer.strip().upper() == "Y"
        self.output("Разрешено пользователем" if allowed else "ОТКЛОНЕНО: действие не выполнено")
        return allowed

    @staticmethod
    def available(module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            return False

    def ensure_dependency(self, module: str, *, required: bool = False) -> bool:
        """При отсутствии — PAUSE + Y/N; затем только заранее заданный pip аргумент.

        Если отказано: возвращаем False для optional и PermissionDenied для required.
        Никакие команды из результатов VLM не принимаются.
        """
        if self.available(module):
            return True
        if module not in DEPENDENCIES:
            raise ValueError(f"Зависимость {module!r} не зарегистрирована в политике безопасности")
        dep = DEPENDENCIES[module]
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", dep.requirement]
        request = PermissionRequest(
            title=f"Установить Python-пакет {dep.requirement}",
            exact_action=" ".join(cmd),
            technical_reason=dep.purpose + "; модуль отсутствует в текущем Python",
            user_benefit=dep.benefit,
            risks=dep.risks + "; pip также может скачать транзитивные зависимости",
            risk=Risk.MEDIUM,
        )
        if not self.approve(request):
            if required:
                raise PermissionDenied(f"Обязательная зависимость {dep.requirement} не установлена")
            return False
        try:
            result = self.runner(cmd, check=False, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SetupFailed(f"Установка {dep.requirement} завершилась с ошибкой") from exc
        if result.returncode != 0:
            raise SetupFailed(f"pip вернул код {result.returncode} для {dep.requirement}")
        if not self.available(module):
            raise SetupFailed(f"Пакет {dep.requirement} установлен, но его импорт не обнаружен")
        return True

    def require_external_action(self, *, title: str, exact_action: str,
                                technical_reason: str, user_benefit: str,
                                risks: str, risk: Risk = Risk.MEDIUM) -> bool:
        """Для Serial/HID, облачной передачи, модели или ручной системной настройки.

        Метод только спрашивает. Исполнитель должен дополнительно проверить `True`.
        """
        return self.approve(PermissionRequest(title, exact_action,
                                              technical_reason, user_benefit,
                                              risks, risk))

    def ensure_ollama_model(self, model: str, *, available_models: set[str],
                            ollama_path: str = "ollama") -> bool:
        """Загрузка возможна только для вручную разрешённых имён и после Y.

        Метод не вызывается автоматически при старте; разработчик определяет,
        какую модель просить. Не исполнять имена, полученные от VLM.
        """
        approved = {"qwen2.5vl:3b"}
        if model in available_models:
            return True
        if model not in approved:
            raise ValueError("Модель не входит в белый список: нужен аудит источника")
        if not self.require_external_action(
            title="Загрузить локальную модель VLM",
            exact_action=f"{ollama_path} pull {model}",
            technical_reason="локальные веса не обнаружены; без них VLM не сможет анализировать изображения",
            user_benefit="можно анализировать кадры без отправки их в облако",
            risks="сетевая загрузка нескольких ГБ; место на диске и возможные условия лицензии модели",
            risk=Risk.MEDIUM,
        ):
            return False
        result = self.runner([ollama_path, "pull", model], check=False, timeout=3600)
        if result.returncode != 0:
            raise SetupFailed(f"Не удалось скачать модель {model}")
        return True
