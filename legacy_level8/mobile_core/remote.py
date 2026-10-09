"""REST API смартфона. Сервер по умолчанию выключен и слушает loopback."""
from __future__ import annotations
import base64,hashlib,hmac,json,os
from pathlib import Path

class RemoteControlServer:
    def __init__(self,agent,token:str,staging_dir='data/staging',enable_frames=False):
        if not token or len(token)<24:raise ValueError('Требуется случайный длинный токен')
        self.agent=agent;self.token=token;self.enable_frames=enable_frames
        self.staging_dir=Path(staging_dir)
    def create_app(self):
        # FastAPI не импортируется до согласованной установки.
        from fastapi import FastAPI,HTTPException,Header,Body,WebSocket,WebSocketDisconnect
        import asyncio
        from fastapi.responses import Response
        from pydantic import BaseModel
        app=FastAPI(title='Phone Agent Monitor',docs_url=None,redoc_url=None,openapi_url=None)
        class Target(BaseModel):name:str
        def auth(authorization):
            if not authorization or not hmac.compare_digest(authorization,'Bearer '+self.token):
                raise HTTPException(status_code=401,detail='Unauthorized')
        @app.get('/status')
        def status(authorization:str|None=Header(None)):
            auth(authorization);return self.agent.status()
        @app.websocket('/ws')
        async def events(ws:WebSocket):
            # Нет токенов в URL/логах; WebSocket ожидает Bearer в заголовке.
            bearer=ws.headers.get('authorization','')
            if not hmac.compare_digest(bearer,'Bearer '+self.token):
                await ws.close(code=1008)
                return
            await ws.accept()
            try:
                while True:
                    await ws.send_json(self.agent.status())
                    await asyncio.sleep(1)
            except WebSocketDisconnect:
                return
            except Exception:
                await ws.close()
        @app.post('/pause')
        def pause(authorization:str|None=Header(None)):
            auth(authorization);self.agent.pause();return {'paused':True}
        @app.post('/panic')
        def panic(authorization:str|None=Header(None)):
            auth(authorization);self.agent.panic();return {'panic':True}
        @app.post('/resume')
        def resume(authorization:str|None=Header(None)):
            auth(authorization)
            # Требуется предыдущее отдельное одобрение на самом телефоне.
            self.agent.security.require('remote_resume')
            if not self.agent.resume():raise HTTPException(409,'Нужна локальная разблокировка EmergencyStop')
            return {'paused':False}
        @app.post('/set_target')
        def target(payload:Target,authorization:str|None=Header(None)):
            auth(authorization);self.agent.security.require('remote_target')
            if payload.name not in ('quest','farm','explore','combat'):
                raise HTTPException(400,'Неизвестная задача')
            self.agent.tactician.tasks.put(payload.name)
            return {'queued':payload.name}
        @app.get('/frame')
        def frame(authorization:str|None=Header(None)):
            auth(authorization)
            if not self.enable_frames:raise HTTPException(403,'Передача изображения выключена')
            data=self.agent.last_observation.screenshot_jpeg if self.agent.last_observation else None
            if not data:raise HTTPException(404,'Нет кадра')
            return Response(content=data,media_type='image/jpeg',headers={'Cache-Control':'no-store'})
        @app.post('/stage_update')
        def stage_update(body:bytes=Body(...,media_type='application/octet-stream'),
                         authorization:str|None=Header(None),x_sha256:str|None=Header(None)):
            auth(authorization);self.agent.security.require('stage_update')
            if len(body)>2_000_000 or not body.startswith(b'PK\x03\x04'):
                raise HTTPException(400,'Разрешены только ZIP менее 2 МБ')
            digest=hashlib.sha256(body).hexdigest()
            if not x_sha256 or not hmac.compare_digest(x_sha256.lower(),digest):raise HTTPException(400,'SHA256 mismatch')
            self.staging_dir.mkdir(parents=True,exist_ok=True)
            dest=self.staging_dir/(digest+'.zip')
            # Только сохраняем на проверку. НЕ распаковываем и НЕ выполняем.
            dest.write_bytes(body)
            return {'staged':True,'sha256':digest,'activated':False}
        return app
    def serve(self,host='127.0.0.1',port=8765):
        if host!='127.0.0.1':
            raise PermissionError('Прямой LAN доступ запрещён: используйте авторизованный ADB port forward')
        import uvicorn
        uvicorn.run(self.create_app(),host=host,port=port,log_level='warning')
