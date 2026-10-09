"""Безопасная точка тяжёлого анализа; никакого исполнения кода по запросу."""
from __future__ import annotations
import hmac,os,base64

def create_app(analyzer=None):
    from fastapi import FastAPI,Header,HTTPException
    from pydantic import BaseModel
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    class Job(BaseModel):question:str;image_b64:str
    @app.post('/infer')
    def infer(job:Job,authorization:str|None=Header(None)):
        token=os.getenv('GAME_OFFLOAD_TOKEN','')
        if not token or not authorization or not hmac.compare_digest(authorization,'Bearer '+token):
            raise HTTPException(401,'Unauthorized')
        if job.question not in ('scene','risk','quest'):raise HTTPException(400,'Недопустимая задача')
        if len(job.image_b64)>1_500_000:raise HTTPException(413,'Изображение слишком большое')
        jpeg=base64.b64decode(job.image_b64,validate=True)
        if not jpeg.startswith(b'\xff\xd8'):raise HTTPException(400,'Требуется JPEG')
        if analyzer is None:
            raise HTTPException(503,'Модель не подключена; мобильный fallback работает')
        # analyzer заранее доверен/запущен пользователем; не выполняем полученный код.
        return analyzer(jpeg,job.question)
    return app
