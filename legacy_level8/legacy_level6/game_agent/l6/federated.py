"""Передача ограниченных данных об игровых навыках с одноразовым согласием.

Это PSEUDONYMIZATION, а не доказанная анонимность. Скриншоты, координаты
пользователя, API-ключи и исполняемый код НИКОГДА не экспортируются.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import hashlib
import hmac
import json
import math
import secrets
import time


@dataclass(frozen=True)
class SkillVector:
    game_tag: str
    skill_tag: str
    embedding: tuple[float, ...]
    confidence: float


@dataclass(frozen=True)
class UIAnchor:
    """Не фотография и не OCR: только согласованная карта известных UI-элементов."""
    game_tag: str
    kind: str
    x: float
    y: float


class FederatedHub:
    """Обмен по HTTPS; только при явном разрешении владельца.

    Сервер должен проверять HMAC, размер и время сообщения; этот клиент
    проверяет ответ и помещает чужие записи в карантин до ручного принятия.
    """
    def __init__(self, secret: bytes, endpoint: str | None = None):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError('Нужен отдельный случайный ключ не короче 32 байт')
        self._secret = secret
        self.endpoint = endpoint
        self.quarantine: list[SkillVector] = []
        self.accepted: list[SkillVector] = []
        self._seen: set[str] = set()
        self._nonces = deque(maxlen=1000)
        self.ui_quarantine: list[UIAnchor] = []

    @staticmethod
    def clean(row: SkillVector):
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]{2,48}',row.game_tag) or not re.fullmatch(r'[a-zA-Z0-9_-]{2,48}',row.skill_tag):
            raise ValueError('Теги должны быть обезличенными идентификаторами')
        if len(row.embedding) != 16 or not all(type(x) in (int,float) and math.isfinite(x) and -1 <= x <= 1 for x in row.embedding):
            raise ValueError('Допускается только нормированный 16-мерный вектор')
        if not 0 <= row.confidence <= 1:
            raise ValueError('Некорректная уверенность')
        return row

    def _mac(self, payload: dict) -> str:
        message=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        return hmac.new(self._secret,message,hashlib.sha256).hexdigest()

    @staticmethod
    def clean_anchor(anchor: UIAnchor) -> UIAnchor:
        import re
        if (not re.fullmatch(r'[A-Za-z0-9_-]{2,48}',anchor.game_tag) or
            anchor.kind not in {'heal_button','quest_button','map_button','battle_button'} or
            not all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1
                    for v in (anchor.x,anchor.y))):
            raise ValueError('Некорректный UI-якорь')
        return anchor

    def envelope(self, skills: list[SkillVector], *, approved: bool=False,
                 screen_map: list[UIAnchor] | None = None) -> dict:
        if not approved:
            raise PermissionError('Передача без разрешения запрещена')
        if len(skills)>25:
            raise ValueError('Слишком много векторов')
        rows=[]
        for row in skills:
            self.clean(row)
            rows.append({'game_tag':row.game_tag,'skill_tag':row.skill_tag,
                         'embedding':[round(x,4) for x in row.embedding],
                         'confidence':round(row.confidence,3)})
        anchors=[]
        for anchor in (screen_map or []):
            if len(anchors)>=25: raise ValueError('Не более 25 UI-якорей')
            self.clean_anchor(anchor)
            anchors.append({'game_tag':anchor.game_tag,'kind':anchor.kind,
                            'x':round(anchor.x,3),'y':round(anchor.y,3)})
        message={'schema':2,'timestamp':int(time.time()),'nonce':secrets.token_hex(12),
                 'skills':rows,'screen_map':anchors}
        return {'payload':message,'mac':self._mac(message)}

    def ingest(self, envelope: dict):
        """Проверка подписи и карантин. Никаких новых игровых навыков не включаем."""
        if not isinstance(envelope,dict) or set(envelope)!={'payload','mac'}:
            raise ValueError('Некорректный контейнер')
        payload = envelope['payload']
        if not isinstance(payload,dict) or set(payload) != {'schema','timestamp','nonce','skills','screen_map'} or payload['schema'] != 2:
            raise ValueError('Неверная схема')
        if abs(time.time()-payload['timestamp']) > 300:
            raise ValueError('Устаревшее сообщение')
        if not isinstance(payload['nonce'],str) or len(payload['nonce'])!=24:
            raise ValueError('Неверный nonce')
        if payload['nonce'] in self._seen:
            raise ValueError('Повторное сообщение')
        if not hmac.compare_digest(self._mac(payload),envelope['mac']):
            raise ValueError('Неверная подпись')
        if not isinstance(payload['skills'],list) or len(payload['skills'])>25:
            raise ValueError('Слишком много записей')
        incoming=[]
        for data in payload['skills']:
            if set(data)!={'game_tag','skill_tag','embedding','confidence'}:
                raise ValueError('В сообщении есть посторонние данные')
            incoming.append(self.clean(SkillVector(data['game_tag'],data['skill_tag'],
                                                    tuple(data['embedding']),data['confidence'])))
        if not isinstance(payload['screen_map'],list) or len(payload['screen_map'])>25:
            raise ValueError('Некорректная UI-карта')
        anchors=[]
        for item in payload['screen_map']:
            if set(item)!={'game_tag','kind','x','y'}:
                raise ValueError('Посторонние поля UI-карты')
            anchors.append(self.clean_anchor(UIAnchor(**item)))
        if len(self._nonces)==self._nonces.maxlen:
            self._seen.discard(self._nonces.popleft())
        self._seen.add(payload['nonce'])
        self._nonces.append(payload['nonce'])
        self.quarantine.extend(incoming)
        self.ui_quarantine.extend(anchors)
        return len(incoming) + len(anchors)

    def accept(self, index:int, *, approved:bool=False):
        if not approved:
            raise PermissionError('Нужно подтверждение для импорта навыка')
        row=self.quarantine.pop(index)
        self.accepted.append(row)
        return row

    def exchange(self, skills:list[SkillVector], *, gate, timeout=5,
                 screen_map:list[UIAnchor]|None=None):
        """Сначала разрешение, затем один HTTPS POST. Секрет не отправляем."""
        url=self.endpoint or ''
        parsed=urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Требуется заранее заданный HTTPS endpoint')
        approved = gate.require_external_action(
            title='Синхронизировать обезличенные векторы навыков',
            exact_action=f'HTTPS POST {url}; {len(skills)} векторов и {len(screen_map or [])} UI-якорей',
            technical_reason='Передать игровые тактики другим агентам',
            user_benefit='Проверенные тактики можно повторно использовать на других устройствах',
            risks='Могут раскрываться игровые предпочтения и структура UI; сервер хранит метаданные и IP-адрес')
        if not approved: return False
        message=self.envelope(skills,approved=True,screen_map=screen_map)
        body=json.dumps(message,separators=(',',':')).encode()
        if len(body) > 16_384: raise ValueError('Слишком большое сообщение')
        req=Request(url,data=body,headers={'Content-Type':'application/json'},method='POST')
        with urlopen(req,timeout=timeout) as response:
            data=response.read(16_385)
        if len(data)>16_384: raise ValueError('Слишком большой ответ сервера')
        result=json.loads(data)
        self.ingest(result)
        return True
