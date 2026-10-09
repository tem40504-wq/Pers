"""Опциональный offload, никогда не обязателен для действия."""
from __future__ import annotations
import asyncio,urllib.request,json,base64

class ComputeOffloadProxy:
    def __init__(self,endpoint:str,token:str,enabled=False,timeout=1.2):
        self.endpoint=endpoint.rstrip('/')
        self.token=token;self.enabled=enabled;self.timeout=timeout
        self.sem=asyncio.Semaphore(1)
    async def analyze(self,jpeg:bytes,local_fallback,question:str='scene'):
        if not self.enabled:return await local_fallback(jpeg)
        async with self.sem:
            def request():
                body=json.dumps({'question':question,'image_b64':base64.b64encode(jpeg).decode()}).encode()
                req=urllib.request.Request(self.endpoint+'/infer',body,
                      headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method='POST')
                with urllib.request.urlopen(req,timeout=self.timeout) as r:
                    return json.loads(r.read(2_000_000))
            try:
                return await asyncio.wait_for(asyncio.to_thread(request),timeout=self.timeout+.2)
            except (Exception):
                return await local_fallback(jpeg)
