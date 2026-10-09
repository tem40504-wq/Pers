"""Проверка зависимостей ДО импорта cv2/numpy и остальных пакетов игры."""
from __future__ import annotations
import shutil
from .security import PermissionGate, PermissionDenied, Risk


def preflight(gate: PermissionGate, *, ocr=False, yolo=False, chroma=False,
              onnx=False, hid=False) -> dict[str, bool]:
    """Обязательные зависимости требуют разрешённой установки или остановки.

    Optional-слои при отказе отключаются без нарушения работы ядра.
    """
    for name in ("numpy", "cv2", "PIL", "requests"):
        gate.ensure_dependency(name, required=True)

    result = {}
    for enabled, module, name in (
        (ocr, "easyocr", "ocr"),
        (yolo, "ultralytics", "yolo"),
        (chroma, "chromadb", "chroma"),
        (onnx, "onnxruntime", "onnx"),
        (hid, "serial", "hid"),
    ):
        result[name] = gate.ensure_dependency(module, required=False) if enabled else False
    return result


def check_adb(gate: PermissionGate, adb_path="adb") -> bool:
    if shutil.which(adb_path):
        return True
    gate.require_external_action(
        title="Установить Android SDK Platform-Tools вручную",
        exact_action="Открыть https://developer.android.com/tools/releases/platform-tools и установить ADB самостоятельно",
        technical_reason="команда adb не найдена; нельзя получить кадр и управлять телефоном",
        user_benefit="безопасное подключение Android через официальный инструмент",
        risks="USB-отладка предоставляет авторизованному ПК расширенный доступ к устройству; выключайте после теста",
        risk=Risk.HIGH,
    )
    # ОС агент НЕ изменяет — пользователь устанавливает инструменты самостоятельно.
    return False
