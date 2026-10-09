"""SmolVLM через установленный владельцем локальный llama.cpp-сервер в Termux.
Не скачивает ни сервер, ни модель. При ошибке возвращает «неизвестно».
"""
from __future__ import annotations
import base64,json,urllib.request

class LocalSmolVLM:
    def __init__(self,url='http://127.0.0.1:8080',model='smolvlm',timeout=3.0):
        if not url.startswith('http://127.0.0.1:'):raise ValueError('Локальная модель: только loopback')
        self.url=url.rstrip('/');self.model=model;self.timeout=timeout
    def __call__(self,jpeg:bytes):
        payload={'model':self.model,'messages':[{'role':'user','content':[
          {'type':'text','text':'Определи игровую сцену: battle, menu, quest, victory или unknown. Верни JSON {"scene":"...", "confidence":0..1}.'},
          {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode()}}]}],
          'max_tokens':60,'temperature':0}
        req=urllib.request.Request(self.url+'/v1/chat/completions',json.dumps(payload).encode(),
           {'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as r:
                result=json.load(r)
            return json.loads(result['choices'][0]['message']['content'])
        except Exception:return {'scene':'unknown','confidence':0.0}
