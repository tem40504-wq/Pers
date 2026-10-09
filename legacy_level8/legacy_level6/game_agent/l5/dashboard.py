"""Локальная панель FastAPI: только 127.0.0.1, без сторонних CDN.

PANIC STOP блокирует новые действия на следующей точке проверки.
Физически прервать уже отправленный ADB/HID жест невозможно гарантированно.
"""
from __future__ import annotations
from collections import deque
from threading import Event, RLock, Thread
import secrets
import time

PAGE = '''<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Game Agent Level 5</title>
<style>body{background:#10151d;color:#e7ecf6;font:15px system-ui;margin:24px}
main{max-width:1100px;margin:auto}button,input,select{font:inherit;margin:5px;padding:10px}
button.stop{background:#bb233e;color:white;border:0;padding:17px;font-weight:bold}
section{background:#202935;border-radius:12px;margin:15px 0;padding:15px}
img{max-width:100%;border-radius:8px}pre{white-space:pre-wrap;word-break:break-word}</style>
<main><h1>Universal Game Agent — Level 5</h1>
<button class="stop" onclick="send('/api/panic',{})">PANIC STOP</button>
<label>Детализация <select id="v" onchange="send('/api/verbosity',{level:+this.value})">
<option value="0">0 — действия</option><option selected value="1">1 — кратко</option>
<option value="2">2 — анализ</option><option value="3">3 — отладка</option></select></label>
<section><h2>Кадр и bounding boxes</h2><img id="frame" alt="Ожидается кадр"><div id="status"></div></section>
<section><h2>Наблюдения и объяснения решений (не скрытые мысли)</h2><pre id="details"></pre></section>
<section><h2>Вопрос оператору</h2><input id="question" placeholder="Почему ты не используешь ульту?">
<button onclick="send('/api/ask',{question:document.getElementById('question').value})">Спросить</button><p id="response"></p></section>
<section><h2>Коррекция поведения</h2><input id="feedback" placeholder="Не пей зелье, беги!">
<button onclick="send('/api/feedback',{message:document.getElementById('feedback').value})">Отправить</button></section>
<section><h2>Связи роя и журнал безопасности</h2><pre id="graph"></pre></section></main>
<script>
async function send(path,body){try{let r=await fetch(path,{method:'POST',headers:{'content-type':'application/json','x-agent-token':'__TOKEN__'},body:JSON.stringify(body)});
document.getElementById('response').textContent=JSON.stringify(await r.json())}catch(e){alert(e)}}
async function poll(){try{let r=await fetch('/api/status');let v=await r.json();
document.getElementById('details').textContent=JSON.stringify(v.operator,null,2);
document.getElementById('graph').textContent=JSON.stringify({swarm:v.swarm,safety:v.operator.safety},null,2);
document.getElementById('status').textContent='Кадр: '+v.frame_at+' | PANIC: '+v.operator.panic;
if(v.has_frame)document.getElementById('frame').src='/api/frame?t='+Date.now();}catch(e){} }
setInterval(poll,1000);poll();</script></html>'''

class XAI_Dashboard:
    def __init__(self, operator, panic_event: Event | None = None):
        self.operator=operator
        self.panic_event=panic_event or operator.panic_event
        self.lock=RLock()
        self.frame=b""
        self.frame_at=0.
        self.swarm=deque(maxlen=100)
        self.server=None
        self.token=secrets.token_urlsafe(24)

    def push_frame(self, jpeg: bytes):
        with self.lock:
            self.frame=bytes(jpeg)
            self.frame_at=time.time()

    def push_swarm(self, sender, receiver, kind, summary):
        with self.lock:
            self.swarm.append({"time":time.time(),"from":sender,"to":receiver,
                              "kind":str(kind)[:30],"summary":str(summary)[:200]})

    def stop(self):
        # Самая быстрая операция: сразу выставляем потокобезопасный флаг.
        self.panic_event.set()
        self.operator.safety_log.append("PANIC STOP активирован оператором")
        return {"stopped":True,"warning":"Активная операция может завершиться до остановки"}

    def snapshot(self):
        with self.lock:
            return {"operator":self.operator.compact(),"swarm":list(self.swarm)[-20:],
                    "has_frame":bool(self.frame),"frame_at":round(self.frame_at,2)}

    def app(self):
        # FastAPI/uvicorn — только опционально, после Y через PermissionGate.
        from fastapi import FastAPI, Header, HTTPException
        from fastapi.responses import HTMLResponse, Response
        from pydantic import BaseModel, Field
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        api=FastAPI(title="Universal Game Agent Level 5",docs_url=None,redoc_url=None)
        api.add_middleware(TrustedHostMiddleware,allowed_hosts=["localhost", "127.0.0.1"])
        def require_token(value):
            if value != dash.token: raise HTTPException(status_code=403,detail="Invalid operator token")
        dash=self
        class Message(BaseModel):
            message: str = Field(max_length=200)
        class Question(BaseModel):
            question: str = Field(max_length=300)
        class Verbosity(BaseModel):
            level: int
        @api.get("/",response_class=HTMLResponse)
        def index():return PAGE.replace("__TOKEN__",dash.token)
        @api.get("/api/status")
        def status():return dash.snapshot()
        @api.get("/api/frame")
        def frame():
            with dash.lock:
                data=dash.frame
            return Response(content=data,media_type="image/jpeg",
                            headers={"Cache-Control":"no-store"})
        @api.post("/api/panic")
        def panic(x_agent_token: str | None = Header(default=None)):
            require_token(x_agent_token)
            return dash.stop()
        @api.post("/api/verbosity")
        def verbosity(item:Verbosity,x_agent_token: str | None = Header(default=None)):
            require_token(x_agent_token)
            try:return {"level":dash.operator.set_verbosity(item.level)}
            except ValueError:return {"error":"Уровень должен быть 0–3"}
        @api.post("/api/feedback")
        def feedback(item:Message,x_agent_token: str | None = Header(default=None)):
            require_token(x_agent_token)
            return {"reply":dash.operator.receive_feedback(item.message)}
        @api.post("/api/ask")
        def ask(item:Question,x_agent_token: str | None = Header(default=None)):
            require_token(x_agent_token)
            return {"reply":dash.operator.answer_operator_question(item.question)}
        return api

    def serve(self, port=8765):
        import uvicorn
        if not (1024 <= port <= 65535):
            raise ValueError("Некорректный локальный порт")
        # Важное ограничение: только localhost, без сетевой публикации дашборда.
        conf=uvicorn.Config(self.app(),host="127.0.0.1",port=port,log_level="warning")
        self.server=uvicorn.Server(conf)
        thread=Thread(target=self.server.run,daemon=True,name="L5Dashboard")
        thread.start()
        return thread

    def close(self):
        if self.server is not None:
            self.server.should_exit=True

    def annotate(self, image_jpeg, boxes):
        """Возвращает JPEG с ограниченным количеством рамок для панели."""
        import cv2
        import numpy as np
        frame=cv2.imdecode(np.frombuffer(image_jpeg,np.uint8),cv2.IMREAD_COLOR)
        if frame is None: return
        for box in list(boxes)[:50]:
            cv2.rectangle(frame,(int(box.x1),int(box.y1)),(int(box.x2),int(box.y2)),(80,210,190),2)
            cv2.putText(frame,str(box.label)[:20],(int(box.x1),max(15,int(box.y1)-3)),
                        cv2.FONT_HERSHEY_SIMPLEX,.5,(80,210,190),1)
        ok,jpg=cv2.imencode(".jpg",frame,[int(cv2.IMWRITE_JPEG_QUALITY),70])
        if ok:self.push_frame(jpg.tobytes())
