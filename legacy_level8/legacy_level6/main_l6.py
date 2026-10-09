"""Безопасный запуск Level 5: сначала PermissionGate, затем любые импорты CV/ML.

Запуск без --execute = dry-run. Новые веса, библиотеки и устройство аудио
не устанавливаются/не открываются без явного разрешения оператора.
"""
from __future__ import annotations
import argparse
import json
import logging
import os
from pathlib import Path

from game_agent.l4.security import PermissionGate, PermissionDenied, SetupFailed, Risk
from game_agent.l4.bootstrap import preflight, check_adb
from main_l4 import prepare_local_model, roi


def parser():
    p=argparse.ArgumentParser(description="Universal Game Agent — Level 6")
    p.add_argument("--device", help="серийный номер ADB")
    p.add_argument("--game", default="generic")
    p.add_argument("--goal", default="исследовать безопасно")
    p.add_argument("--ocr", action="store_true")
    p.add_argument("--yolo", action="store_true")
    p.add_argument("--weights")
    p.add_argument("--chroma", action="store_true")
    p.add_argument("--execute", action="store_true", help="РАЗРЕШИТЬ реальные нажатия")
    p.add_argument("--dashboard", action="store_true", help="локальная панель localhost")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--verbosity", type=int,choices=(0,1,2,3),default=1)
    p.add_argument("--hp-roi",type=roi)
    p.add_argument("--mp-roi",type=roi)
    p.add_argument("--local-model",default="qwen2.5vl:3b")
    p.add_argument("--audio-device",type=int,help="выбранный пользователем вход PCM на ПК")
    p.add_argument("--audio-model",type=Path,help="проверенная YAMNet TFLite модель")
    p.add_argument("--audio-map",type=Path,help="JSON соответствия игровых событий классам модели")
    p.add_argument("--max-steps",type=int,default=5)
    p.add_argument("--preflight-only",action="store_true")
    return p


def main():
    args=parser().parse_args()
    if args.max_steps < 0:
        raise ValueError("--max-steps >= 0")
    if args.yolo and not args.weights:
        raise ValueError("--yolo требует --weights")
    gate=PermissionGate()
    caps=preflight(gate,ocr=args.ocr,yolo=args.yolo,chroma=args.chroma)
    if args.dashboard:
        caps["dashboard"]=(gate.ensure_dependency("fastapi") and gate.ensure_dependency("uvicorn"))
        if not caps["dashboard"]:print("[fallback] Нет FastAPI: объяснения доступны в консоли")
    else:
        caps["dashboard"]=False
    caps["audio"]=False
    if args.audio_device is not None:
        if args.audio_model is None or args.audio_map is None or not args.audio_model.is_file() or not args.audio_map.is_file():
            print("[fallback] Нет проверенной YAMNet или карты меток: звук отключён")
        elif gate.ensure_dependency("sounddevice") and gate.ensure_dependency("tflite_runtime"):
            caps["audio"] = gate.require_external_action(
                title="Активировать звуковой вход ПК",
                exact_action=f"Захват PCM с локального устройства #{args.audio_device} и анализ {args.audio_model}",
                technical_reason="для определения игровых звуков необходимо получить PCM поток",
                user_benefit="можно получать сигналы о событиях без ожидания кадра",
                risks="может записываться окружающий звук; устройство и модель надо проверить; дополнительная нагрузка CPU",
                risk=Risk.HIGH)
    if args.preflight_only:
        print("Проверка разрешений завершена. Телефон не использовался.")
        return
    if not check_adb(gate,os.getenv("ADB_PATH","adb")):
        raise PermissionDenied("Нет ADB. Установите вручную и повторите запуск")

    # Импорты после preflight. Программное обеспечение без Y не ставится.
    from game_agent.config import Settings
    from game_agent.adb import ADBDevice
    from game_agent.l5.agent_l5 import AudioWorker
    from game_agent.l6.agent_l6 import Level6Agent
    from game_agent.l5.audio import AudioPerception, ApprovedAudioInput, TFLiteYAMNetAdapter
    from game_agent.l5.operator import OperatorAssistant
    from game_agent.l5.dashboard import XAI_Dashboard
    from threading import Event

    audio=AudioPerception()
    source=None
    audio_worker=None
    if caps["audio"]:
        try:
            class_map=json.loads(args.audio_map.read_text(encoding="utf-8"))
            classifier=TFLiteYAMNetAdapter(args.audio_model,class_map)
            audio=AudioPerception(classifier)
            audio_worker=AudioWorker(audio)
            source=ApprovedAudioInput(args.audio_device)
            audio_worker.start()
            source.start(audio_worker.submit)
        except Exception as ex:
            print(f"[fallback] Аудио отключено: {ex}")
            if source:source.close()
            if audio_worker:audio_worker.close()
            audio=AudioPerception()
    local=prepare_local_model(gate,args.local_model)
    cfg=Settings(serial=args.device,game_id=args.game,user_goal=args.goal,
        dry_run=not args.execute,enable_ocr=caps["ocr"],enable_yolo=caps["yolo"],
        yolo_weights=args.weights if caps["yolo"] else None,
        enable_chroma=caps["chroma"],max_steps=args.max_steps,
        vlm_provider="ollama",vlm_model=args.local_model)
    operator=OperatorAssistant(verbosity=args.verbosity)
    dashboard=XAI_Dashboard(operator)
    agent=Level6Agent(cfg,device=ADBDevice(cfg.adb_path,cfg.serial),
                     hp_roi=args.hp_roi,mp_roi=args.mp_roi,local_vlm=local,
                     operator=operator,dashboard=dashboard,audio=audio)
    try:
        if caps["dashboard"]:
            dashboard.serve(args.port)
            print(f"Панель: http://127.0.0.1:{args.port}")
        print("Запуск L6:","ИСПОЛНЕНИЕ" if args.execute else "DRY-RUN без нажатий")
        agent.run(args.max_steps)
    finally:
        if source:source.close()
        if audio_worker:audio_worker.close()
        dashboard.close()
        agent.shutdown()

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    try:main()
    except (PermissionDenied,SetupFailed,ValueError) as ex:print("ОСТАНОВЛЕНО:",ex)
    except KeyboardInterrupt:print("Остановлено пользователем")
