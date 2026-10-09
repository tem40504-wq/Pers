"""Безопасный CLI для Termux. Ничего не ставит и не скачивает автоматически."""
from __future__ import annotations
import argparse,asyncio,os,secrets
from pathlib import Path
from .security import EmergencyStop,SecurityCore,AuditLogger
from .tactician import Tactician,SkillLibrary
from .perception import MobilePerception
from .memory import MobileMemory
from .bridge import AccessibilityController
from .agent import MobileAgent
from .contracts import Mode
from .offload import ComputeOffloadProxy

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=[x.value for x in Mode],default=Mode.AUTONOMOUS.value)
    p.add_argument('--bridge-token',default=os.getenv('GAME_BRIDGE_TOKEN'))
    p.add_argument('--remote-token',default=os.getenv('GAME_REMOTE_TOKEN'))
    p.add_argument('--skills',default='examples/skills.json')
    p.add_argument('--safe-box',action='append',default=[],help='x1,y1,x2,y2; только разрешённые зоны')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--remote',action='store_true',help='REST панель, выключена по умолчанию')
    p.add_argument('--share-frames',action='store_true')
    p.add_argument('--steps',type=int,default=5)
    p.add_argument('--offload-url',default='',help='HTTPS ПК либо 127.0.0.1 через ADB reverse')
    p.add_argument('--allow-remote-resume',action='store_true')
    p.add_argument('--allow-stage-update',action='store_true')
    p.add_argument('--allow-remote-target',action='store_true')
    args=p.parse_args()
    if not args.bridge_token:raise SystemExit('Сначала введите токен, показанный Android Companion (GAME_BRIDGE_TOKEN)')
    stop=EmergencyStop(300)
    keyfile=Path('data/audit.key')
    keyfile.parent.mkdir(parents=True,exist_ok=True)
    if os.getenv('GAME_AUDIT_KEY'):
        secret=bytes.fromhex(os.environ['GAME_AUDIT_KEY'])
    elif keyfile.exists():
        secret=bytes.fromhex(keyfile.read_text(encoding='utf-8').strip())
    else:
        secret=secrets.token_bytes(32)
        keyfile.write_text(secret.hex(),encoding='utf-8')
        keyfile.chmod(0o600)
    audit=AuditLogger('data/audit.jsonl',secret)
    security=SecurityCore(stop,audit)
    if args.safe_box:
        security.safe_boxes=[tuple(map(int,item.split(','))) for item in args.safe_box]
        if not all(len(x)==4 for x in security.safe_boxes):raise SystemExit('Неверная safe-box')
    if args.remote or args.mode!=Mode.AUTONOMOUS.value:
        if not security.request('remote', 'Разрешить защищённый локальный API для ПК',
              'Логи и кнопки паузы без прямого управления игрой','Риск доступа к кадрам и журналам'):
            args.remote=False
    if args.share_frames:
        if not security.request('frames','Передача кадров в мониторинг','Визуальная диагностика','Снимки могут содержать личные данные'):
            args.share_frames=False
    if args.allow_remote_resume:
        security.request('remote_resume','Разрешить удалённое RESUME после локального ARM','Можно продолжить после паузы','Возможны ошибочные действия')
    if args.allow_remote_target:
        security.request('remote_target','Принимать приоритетные цели с ПК','Удобнее диагностика задач','Ошибочно выбранная цель')
    if args.allow_stage_update:
        security.request('stage_update','Разрешить только приём ZIP в карантин','Ускоряет просмотр обновлений','Полученный архив может содержать опасный код; не активируется')
    if args.execute:
        if not args.safe_box:raise SystemExit('Для реальных касаний укажите --safe-box')
        if not security.request('execute','Разрешить касания Android Accessibility','Автоматизация проверенных действий',
                      'Ошибочные нажатия, блокировка игрового аккаунта при нарушении правил игры'):
            args.execute=False
        else:stop.arm(True)
    else:stop.arm(True)  # Режим без касаний разрешён локальным запуском скрипта.
    controller=AccessibilityController(args.bridge_token)
    offload=None
    if args.mode==Mode.OFFLOAD.value and args.offload_url:
        if not (args.offload_url.startswith('https://') or args.offload_url.startswith('http://127.0.0.1:')):
            raise SystemExit('Offload требует HTTPS или защищённый ADB reverse на localhost')
        if security.request('offload','Передавать JPEG ПК для тяжёлой VLM','Быстрее сложные анализы','Утечка содержимого экрана; расход трафика'):
            offload=ComputeOffloadProxy(args.offload_url,os.getenv('GAME_OFFLOAD_TOKEN',''),enabled=True)
    agent=MobileAgent(controller,MobilePerception(),Tactician(SkillLibrary(args.skills)),security,
                      MobileMemory(),mode=Mode(args.mode),dry_run=not args.execute,offload=offload)
    if args.remote:
        if not args.remote_token:raise SystemExit('GAME_REMOTE_TOKEN обязателен')
        from .remote import RemoteControlServer
        import threading
        server=RemoteControlServer(agent,args.remote_token,enable_frames=args.share_frames)
        threading.Thread(target=server.serve,daemon=True).start()
    agent.resume()
    try:asyncio.run(agent.run(args.steps))
    except KeyboardInterrupt:agent.panic()

if __name__=='__main__':main()
