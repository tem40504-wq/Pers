"""Level 4 с PermissionGate: stdlib preflight до импорта сторонних библиотек.

НИКОГДА не устанавливает пакеты или скачивает модель до явного ответа Y.
Оригинальный main.py остаётся без изменений.
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import shutil
import subprocess

from game_agent.l4.security import PermissionGate, PermissionDenied, Risk, SetupFailed
from game_agent.l4.bootstrap import check_adb, preflight


def roi(text):
    try:
        t = tuple(map(float, text.split(",")))
        if len(t) != 4 or not 0 <= t[0] < t[2] <= 1 or not 0 <= t[1] < t[3] <= 1:
            raise ValueError()
        return t
    except ValueError as ex:
        raise argparse.ArgumentTypeError("ROI: x1,y1,x2,y2 в диапазоне 0..1") from ex


def origin(text):
    try:
        x, y = (int(v) for v in text.split(","))
        if x < 0 or y < 0:
            raise ValueError()
        return x, y
    except ValueError as ex:
        raise argparse.ArgumentTypeError("HID origin: x,y (неотрицательные координаты)") from ex


class UnavailableVLM:
    """Выключаем локальные запросы, когда пользователь отказался от модели."""
    def ask_json(self, jpeg, prompt, schema=None):
        return {"dsl": "IF False THEN wait()", "confidence": 0.0}


def inspect_ollama_models() -> set[str] | None:
    """Только чтение локального списка моделей. Никаких автоматических загрузок."""
    if not shutil.which("ollama"):
        return None
    try:
        p = subprocess.run(["ollama", "list"], capture_output=True, text=True,
                           timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode:
        return None
    return {line.split()[0] for line in p.stdout.splitlines()[1:] if line.strip()}


def prepare_local_model(gate: PermissionGate, model: str):
    """Устанавливать Ollama из сети агент не вправе: только ручная инструкция."""
    from game_agent.l4.local_vlm import LocalVLM
    models = inspect_ollama_models()
    if models is None:
        print("[fallback] Ollama недоступна — остаются OpenCV, OCR, YOLO и старый Worker.")
        gate.require_external_action(
            title="Установить/запустить Ollama вручную",
            exact_action="Открыть https://ollama.com/download и установить Ollama самостоятельно",
            technical_reason="нет доступной локальной VLM, невозможен анализ сложных сцен",
            user_benefit="обработка кадров локально вместо облачного API",
            risks="системная установка отдельной программы; нагрузка на GPU/CPU",
        )
        return LocalVLM(backend=UnavailableVLM())
    if model not in models:
        try:
            if not gate.ensure_ollama_model(model, available_models=models):
                print("[fallback] Пользователь отказался от модели; локальная VLM выключена.")
                return LocalVLM(backend=UnavailableVLM())
        except (OSError, SetupFailed) as exc:
            print(f"[fallback] Модель недоступна: {exc}")
            return LocalVLM(backend=UnavailableVLM())
    return LocalVLM(model=model)


def main():
    p = argparse.ArgumentParser(description="Universal Game Agent Level 4 / PermissionGate")
    p.add_argument("--device")
    p.add_argument("--game", default="generic")
    p.add_argument("--goal", default="исследовать интерфейс безопасно")
    p.add_argument("--ocr", action="store_true")
    p.add_argument("--yolo", action="store_true")
    p.add_argument("--weights")
    p.add_argument("--chroma", action="store_true")
    p.add_argument("--onnx", action="store_true", help="проверить ONNX-зависимость (потребуются веса и адаптер)")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--cloud", action="store_true", help="разрешение на отправку кадров запрашивается отдельно")
    p.add_argument("--local-model", default="qwen2.5vl:3b")
    p.add_argument("--hid-port", help="например COM5; требует явного разрешения")
    p.add_argument("--hid-origin", type=origin, help="проверенная калибровка x,y указателя HID")
    p.add_argument("--hp-roi", type=roi)
    p.add_argument("--mp-roi", type=roi)
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--preflight-only", action="store_true", help="только проверка зависимостей без ADB")
    args = p.parse_args()
    if args.max_steps < 0:
        p.error("--max-steps должно быть >= 0")
    if args.yolo and not args.weights:
        p.error("Для --yolo нужны веса --weights")
    if args.hid_origin and not args.hid_port:
        p.error("--hid-origin требует --hid-port")

    gate = PermissionGate()
    # Сначала проверяем зависимости и запросы разрешений, без скрытых установок.
    capabilities = preflight(gate, ocr=args.ocr, yolo=args.yolo,
                             chroma=args.chroma, onnx=args.onnx,
                             hid=bool(args.hid_port))
    for feature in ("ocr", "yolo", "chroma", "onnx", "hid"):
        if getattr(args, feature, False) and not capabilities[feature]:
            print(f"[fallback] {feature} отключено: зависимость недоступна/разрешение отклонено")
    if args.preflight_only:
        print("Проверка зависимостей завершена. Телефон не использовался.")
        return

    if not check_adb(gate, os.getenv("ADB_PATH", "adb")):
        raise PermissionDenied("ADB отсутствует. Выполните ручную установку и перезапустите агент")
    if args.cloud and not gate.require_external_action(
        title="Разрешить облачный Vision API на текущую сессию",
        exact_action="Отправлять кадры игры указанному в настройках VLM API",
        technical_reason="локальный анализ может оказаться неуверенным (<0.7)",
        user_benefit="получить дополнительную оценку сложных сцен",
        risks="изображения экрана передаются третьей стороне; возможны расходы и персональные данные",
        risk=Risk.HIGH,
    ):
        args.cloud = False
        print("[fallback] облачная VLM отключена")
    if args.cloud and not os.getenv("VLM_API_KEY"):
        print("[fallback] VLM_API_KEY отсутствует: облачная VLM выключена")
        args.cloud = False

    # Только после preflight импортируем старые модули, которым нужны cv2/numpy.
    from game_agent.config import Settings
    from game_agent.vlm import VLM
    from game_agent.l4.agent_l4 import Level4Agent
    from game_agent.adb import ADBDevice
    from game_agent.l4.hid import (SerialHIDTransport, CalibratedHIDInput,
                                  HIDWithADBFallback)
    local_vlm = prepare_local_model(gate, args.local_model)
    cloud = (VLM("openai", os.getenv("CLOUD_VLM_MODEL", "gpt-4o"),
                 api_key=os.getenv("VLM_API_KEY", "")) if args.cloud else None)
    cfg = Settings(serial=args.device, game_id=args.game, user_goal=args.goal,
                   dry_run=not args.execute, enable_ocr=capabilities["ocr"],
                   enable_yolo=capabilities["yolo"],
                   yolo_weights=args.weights if capabilities["yolo"] else None,
                   enable_chroma=capabilities["chroma"], max_steps=args.max_steps,
                   vlm_provider="ollama", vlm_model=args.local_model)
    device = ADBDevice(cfg.adb_path, cfg.serial)
    hid_port = args.hid_port if capabilities["hid"] else None
    if hid_port:
        if gate.require_external_action(
            title="Открыть HID Serial-порт",
            exact_action=f"Открыть {hid_port} для ограниченного протокола движения/нажатий",
            technical_reason="альтернативный транспорт для тестового оборудования",
            user_benefit="аппаратная совместимость с откалиброванным HID-стендом",
            risks="внешнее устройство может ошибочно отправить ввод; нужен USB Host/OTG",
            risk=Risk.HIGH,
        ):
            transport = SerialHIDTransport(hid_port)
            hid = CalibratedHIDInput(transport,
                  *(args.hid_origin or (None, None)), calibrated=args.hid_origin is not None)
            device = HIDWithADBFallback(device, hid)
        else:
            print("[fallback] пользователь отклонил HID — используется ADB")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("L4: " + ("ИСПОЛНЕНИЕ" if args.execute else "DRY RUN (без нажатий)"))
    Level4Agent(cfg, device=device, hp_roi=args.hp_roi, mp_roi=args.mp_roi,
                local_vlm=local_vlm, cloud_vlm=cloud, allow_cloud=args.cloud).run()


if __name__ == "__main__":
    try:
        main()
    except (PermissionDenied, SetupFailed) as exc:
        print(f"ОСТАНОВЛЕНО: {exc}")
    except KeyboardInterrupt:
        print("Остановлено пользователем")
