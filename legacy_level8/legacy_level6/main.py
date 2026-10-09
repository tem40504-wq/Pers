"""Запуск: py main.py [--ocr] [--chroma] [--execute] [--explore ...]."""
import argparse
from dataclasses import replace
import logging
import os

from game_agent.agent import GameAgent
from game_agent.config import Settings


def main():
    p = argparse.ArgumentParser(description="Universal Cognitive Game Agent v2.0")
    p.add_argument("--device", default=None)
    p.add_argument("--game", default="generic")
    p.add_argument("--goal", default="исследовать интерфейс безопасно")
    p.add_argument("--ocr", action="store_true", help="EasyOCR (нужен для безопасного автопоиска)")
    p.add_argument("--yolo", action="store_true", help="Включить обученную модель YOLO")
    p.add_argument("--weights", help="Путь к собственному best.pt для игрового UI")
    p.add_argument("--chroma", action="store_true", help="Включить векторную память")
    p.add_argument("--execute", action="store_true", help="Разрешить реальные нажатия")
    p.add_argument("--explore", action="store_true", help="Осторожная карта интерфейса")
    p.add_argument("--safe-zone", action="append", default=[], metavar="x1,y1,x2,y2",
                   help="Разрешённая владельцем зона; можно повторять")
    p.add_argument("--max-steps", type=int, default=20, help="0 — бесконечно")
    args = p.parse_args()
    if args.max_steps < 0:
        p.error("--max-steps должен быть >= 0")
    zones = []
    for s in args.safe_zone:
        try:
            points = tuple(int(v) for v in s.split(","))
        except ValueError:
            p.error("Формат --safe-zone: x1,y1,x2,y2")
        if len(points) != 4 or points[0] >= points[2] or points[1] >= points[3] or min(points) < 0:
            p.error("Укажите корректный прямоугольник x1< x2, y1< y2")
        zones.append(points)
    if args.explore and (not args.ocr or not zones):
        p.error("--explore требует --ocr и хотя бы одну --safe-zone")
    if args.yolo and not args.weights:
        p.error("Для --yolo укажите --weights")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Settings(serial=args.device or os.getenv("ADB_SERIAL"), game_id=args.game,
                   user_goal=args.goal, dry_run=not args.execute, enable_ocr=args.ocr,
                   enable_yolo=args.yolo, yolo_weights=args.weights,
                   enable_chroma=args.chroma, safe_zones=tuple(zones),
                   explore=args.explore, max_steps=args.max_steps)
    logging.info("Режим: %s", "REAL ADB INPUT" if args.execute else "DRY RUN")
    GameAgent(cfg).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Остановлено Ctrl+C")
