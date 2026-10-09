"""Здесь сосредоточены все опасные операции и human-in-the-loop."""
from __future__ import annotations
import hmac, hashlib, json, threading, time, secrets
from pathlib import Path
from .contracts import Decision

class PermissionRequired(PermissionError): pass

class EmergencyStop:
    def __init__(self, heartbeat_seconds: float = 300.0):
        self._lock = threading.RLock()
        self._stopped = True  # По умолчанию любые действия выключены.
        self._last = 0.0
        self.timeout = heartbeat_seconds
    def arm(self, approved: bool):
        if not approved: raise PermissionRequired('Требуется явное разрешение на запуск')
        with self._lock:
            self._stopped = False
            self._last = time.monotonic()
    def heartbeat(self, physical_operator: bool):
        # Только локальное действие оператора обновляет таймер, не сообщения ИИ.
        if physical_operator:
            with self._lock: self._last = time.monotonic()
    def panic(self):
        with self._lock: self._stopped = True
    def allowed(self) -> bool:
        with self._lock:
            return (not self._stopped and time.monotonic()-self._last < self.timeout)
    @property
    def stopped(self): return not self.allowed()

class AuditLogger:
    """Цепочка HMAC: обнаруживает модификации, но не является хранилищем WORM."""
    def __init__(self, path: str | Path, secret: bytes):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.secret = secret
        self.lock=threading.Lock()
        self.previous = '0'*64
        if self.path.exists():
            rows=self.path.read_text(encoding='utf-8').splitlines()
            if rows:
                if not self.verify(): raise ValueError('Журнал аудита повреждён: нужна проверка оператора')
                self.previous=json.loads(rows[-1])['sig']
    def append(self, kind: str, details: dict):
        with self.lock:
            rec={'ts':round(time.time(),3),'kind':kind,'details':details,'prev':self.previous}
            body=json.dumps(rec,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            sig=hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest()
            rec['sig']=sig
            with self.path.open('a',encoding='utf-8') as fp:
                fp.write(json.dumps(rec,ensure_ascii=False,sort_keys=True)+'\n')
            self.previous=sig
    def verify(self) -> bool:
        prev='0'*64
        for line in self.path.read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            sig=row.pop('sig')
            if row['prev']!=prev:return False
            body=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            expected=hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig,expected):return False
            prev=sig
        return True

class SecurityCore:
    BLOCKED_TERMS = ('купить','оплатить','удалить','продать','purchase','buy','delete','sell','reset account','logout')
    def __init__(self, emergency: EmergencyStop, audit: AuditLogger | None=None):
        self.emergency=emergency; self.audit=audit
        self.safe_boxes: list[tuple[int,int,int,int]]=[]
        self.approvals: dict[str, bool] = {}
    def request(self, key: str, technical: str, benefit: str, risks: str, callback=input) -> bool:
        print(f'\nРАЗРЕШЕНИЕ [{key}]\nЗачем: {technical}\nПольза: {benefit}\nРиски: {risks}')
        answer=callback('Разрешить только это действие? [Y/N]: ').strip().upper()
        ok=answer=='Y'
        self.approvals[key]=ok
        if self.audit:self.audit.append('permission',{'key':key,'approved':ok})
        return ok
    def require(self, key: str):
        if not self.approvals.get(key,False):raise PermissionRequired(f'{key}: требуется отдельное разрешение')
    def validate(self, d: Decision, obs, known_skill: bool) -> bool:
        if d.kind=='wait':return True
        if not self.emergency.allowed() or not known_skill or d.risk!='safe' or d.confidence<.75:return False
        if any(term in d.reason.lower() for term in self.BLOCKED_TERMS):return False
        if d.kind not in ('tap','swipe'):return False
        points=[(d.x,d.y)] + ([(d.x2,d.y2)] if d.kind=='swipe' else [])
        if not all(0<=x<obs.width and 0<=y<obs.height for x,y in points):return False
        if not all(any(a<=x<=c and b<=y<=e for a,b,c,e in self.safe_boxes) for x,y in points):return False
        return True
