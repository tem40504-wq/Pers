"""Демонстрационный локальный relay. НЕ публиковать в Интернет без TLS,
аутентификации пользователей, лимитов нагрузки, мониторинга и аудита.

Старт только вручную; требует USER_PROVIDED_HMAC_HEX в окружении.
Клиент FederatedHub требует HTTPS: для тестов нескольких ПК нужен
отдельно настроенный владельцем TLS reverse proxy и явное разрешение.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import deque
from threading import Lock
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from game_agent.l6.federated import FederatedHub

key_hex=os.getenv('USER_PROVIDED_HMAC_HEX','')
if len(key_hex)<64:
    raise SystemExit('Нужен ключ из 32+ случайных байтов в USER_PROVIDED_HMAC_HEX')
server_hub=FederatedHub(bytes.fromhex(key_hex))
shared=deque(maxlen=25)
lock=Lock()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path!='/exchange' or int(self.headers.get('Content-Length','0'))>16384:
            self.send_error(413);return
        raw=self.rfile.read(int(self.headers['Content-Length']))
        try:
            envelope=json.loads(raw)
            with lock:
                server_hub.ingest(envelope)
                previous=next((x for x in reversed(shared) if x['mac']!=envelope['mac']),None)
                shared.append(envelope)
                answer=previous or server_hub.envelope([],approved=True)
            output=json.dumps(answer,separators=(',',':')).encode()
        except (ValueError,KeyError,TypeError) as exc:
            self.send_error(400,str(exc));return
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(output)))
        self.end_headers()
        self.wfile.write(output)


if __name__=='__main__':
    print('DEV ONLY: http://127.0.0.1:8766; для сети нужен TLS и авторизованный reverse proxy')
    ThreadingHTTPServer(('127.0.0.1',8766),Handler).serve_forever()
