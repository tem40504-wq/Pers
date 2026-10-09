"""Termux -> локальный Android Companion (не ADB)."""
from __future__ import annotations
import urllib.request, json, base64
from .contracts import Decision

class BridgeError(RuntimeError):pass
class AccessibilityController:
    def __init__(self,token:str,base_url='http://127.0.0.1:8766',timeout=.9):
        if not base_url.startswith('http://127.0.0.1:'):raise ValueError('Android bridge должен слушать только loopback')
        self.base=base_url.rstrip('/');self.token=token;self.timeout=timeout
    def _request(self,path,body=None):
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.base+path,data=data,headers={'Authorization':'Bearer '+self.token,
                   'Content-Type':'application/json'},method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as r:
                if r.status!=200:raise BridgeError(f'HTTP {r.status}')
                return json.loads(r.read(2_000_000))
        except Exception as ex:raise BridgeError(str(ex)) from ex
    def status(self):return self._request('/status')
    def frame(self):
        payload=self._request('/frame')
        return base64.b64decode(payload['jpeg_b64'],validate=True)
    def gesture(self,d:Decision):
        if d.kind not in ('tap','swipe'):return {'accepted':False}
        return self._request('/gesture',{'kind':d.kind,'x':d.x,'y':d.y,'x2':d.x2,'y2':d.y2,
                                         'duration_ms':d.duration_ms})
