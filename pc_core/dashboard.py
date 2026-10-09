"""Локальная панель статуса на stdlib: доступ только через 127.0.0.1 и токен."""
from __future__ import annotations
import html
import json
import secrets
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from .fast_input import PanicStop


class ControlDashboard:
    def __init__(self, emergency: PanicStop, port=8766, token: str | None = None):
        self.emergency=emergency
        self.port=port
        self.token=token or secrets.token_urlsafe(24)
        self.recent=deque(maxlen=50)
        self.lock=threading.Lock()
        self.server=None
        self.thread=None

    def update(self, data: dict):
        with self.lock:
            self.recent.append(dict(data))

    def _handler(self):
        panel=self
        class Handler(BaseHTTPRequestHandler):
            def _allowed(self):
                values=parse_qs(urlparse(self.path).query)
                return secrets.compare_digest(values.get('token',[''])[0],panel.token)

            def do_GET(self):
                if not self._allowed():
                    self.send_error(403)
                    return
                with panel.lock:
                    events=list(panel.recent)
                lines=html.escape(json.dumps(events[-15:],indent=2,ensure_ascii=False))
                safe_token=html.escape(panel.token,quote=True)
                body=f'''<!doctype html><meta charset="utf-8"><title>GameAgent Control</title>
<style>body{{font-family:system-ui;background:#111;color:#eee;padding:20px}}
button{{background:#bd1d1d;color:white;font-size:1.25rem;padding:15px;border:0;border-radius:10px}}
pre{{background:#222;padding:12px;white-space:pre-wrap}}</style>
<h1>Game Agent L9 — контроль ПК</h1><p>Только локальный доступ. Новых установок нет.</p>
<p>PANIC STOP: {'АКТИВЕН' if panel.emergency.is_stopped() else 'не активен'}</p>
<form method="POST" action="/panic?token={safe_token}"><button type="submit">PANIC STOP</button></form>
<h2>Последние решения</h2><pre>{lines}</pre>'''.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store')
                self.end_headers();self.wfile.write(body)

            def do_POST(self):
                if not self._allowed() or urlparse(self.path).path != '/panic':
                    self.send_error(403)
                    return
                panel.emergency.stop()
                self.send_response(303)
                self.send_header('Location','/?token='+panel.token)
                self.end_headers()

            def log_message(self,*args):
                pass
        return Handler

    def start(self):
        if self.server:
            return self.url
        self.server=ThreadingHTTPServer(('127.0.0.1',self.port),self._handler())
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        return self.url

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/?token={self.token}'

    def close(self):
        if self.server:
            self.server.shutdown();self.server.server_close()
            if self.thread:self.thread.join(timeout=2)
            self.server=None
