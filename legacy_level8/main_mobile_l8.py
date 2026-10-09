"""Ручной Termux-запуск Level 8: онлайн только наблюдение; офлайн QA по Y/N.

Не выполняет pip/pkg install, ADB, создание модели или изменение Android-настроек.
"""
from __future__ import annotations
import argparse,asyncio,os,secrets
from pathlib import Path
from mobile_core.bridge import AccessibilityController
from mobile_core.perception import MobilePerception
from mobile_core.tactician import Tactician,SkillLibrary
from mobile_core.memory import MobileMemory
from mobile_core.security import EmergencyStop,SecurityCore,AuditLogger
from stealth.integration import Stage8Agent
from testing.replay import ReplayBuffer
from testing.shadow import ShadowMode


def main():
    p=argparse.ArgumentParser(description='Level 8 Mobile QA — онлайн только наблюдение')
    p.add_argument('--bridge-token',default=os.getenv('GAME_BRIDGE_TOKEN'))
    p.add_argument('--skills',default='examples/skills.json')
    p.add_argument('--safe-box',action='append',default=[])
    p.add_argument('--offline-qa',action='store_true',help='Запрос Y/N на безопасный офлайн-эксперимент')
    p.add_argument('--execute',action='store_true',help='Отдельный Y/N на реальные офлайн-касания')
    p.add_argument('--shadow',action='store_true',help='Только прогноз без ввода')
    p.add_argument('--steps',type=int,default=5)
    p.add_argument('--replay-max-mb',type=int,default=512)
    args=p.parse_args()
    if not args.bridge_token:
        raise SystemExit('Токен Android Companion отсутствует: GAME_BRIDGE_TOKEN')
    if args.steps < 1:raise SystemExit('Для первых тестов требуется конечное число шагов')
    if args.execute and (not args.offline_qa or args.shadow):
        raise SystemExit('Реальные действия только в подтверждённом офлайн-тесте без Shadow Mode')
    if args.execute and not args.safe_box:raise SystemExit('Без --safe-box реальные касания запрещены')
    if args.replay_max_mb<=0:raise SystemExit('Лимит Replay должен быть положительным')
    data=Path('data');data.mkdir(exist_ok=True)
    keyfile=data/'audit.key'
    if keyfile.exists():secret=bytes.fromhex(keyfile.read_text(encoding='utf-8').strip())
    else:
        secret=secrets.token_bytes(32)
        keyfile.write_text(secret.hex(),encoding='utf-8');keyfile.chmod(0o600)
    stop=EmergencyStop(300)
    security=SecurityCore(stop,AuditLogger(data/'audit.jsonl',secret))
    if args.safe_box:
        try:security.safe_boxes=[tuple(map(int,b.split(','))) for b in args.safe_box]
        except ValueError:raise SystemExit('safe-box: нужны целые x1,y1,x2,y2')
        if any(len(box)!=4 or box[0]>=box[2] or box[1]>=box[3] for box in security.safe_boxes):
            raise SystemExit('Неверная зона')
    online=not args.offline_qa
    shadow=ShadowMode() if args.shadow else None
    replay=ReplayBuffer(data/'level8_replay',max_bytes=args.replay_max_mb*1024*1024)
    agent=Stage8Agent(AccessibilityController(args.bridge_token),MobilePerception(),
                     Tactician(SkillLibrary(args.skills)),security,
                     MobileMemory(),online=online,offline_qa=False,
                     shadow=shadow,replay=replay,dry_run=True)
    if args.offline_qa and not agent.enable_offline_qa(callback=input):
        raise SystemExit('Отказ от офлайн-тестирования. Состояние агента не изменено.')
    if args.execute:
        if not security.request('execute',
               'Разрешить только игровые жесты утверждённой офлайн-игры',
               'Проверить совместимость жестов и обнаружение ошибок',
               'Ошибочные нажатия и потеря прогресса; остановка уже выполненного жеста не гарантируется'):
            raise SystemExit('Исполнение не разрешено')
        agent.dry_run=False
    stop.arm(True)
    agent.resume()
    try:asyncio.run(agent.run(args.steps))
    except KeyboardInterrupt:agent.panic()
    finally:replay.close()

if __name__=='__main__':main()
