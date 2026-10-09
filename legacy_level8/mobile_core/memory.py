"""Локальная SQLite-память. FAISS необязателен; падение не блокирует агента."""
from __future__ import annotations
import sqlite3, json, math, time
from pathlib import Path

class MobileMemory:
    def __init__(self,path: str='data/mobile.sqlite3', faiss_index=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.path),check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL,game TEXT,kind TEXT, payload TEXT, vector TEXT)')
        self.db.commit();self.index=faiss_index
    def add(self,game:str,kind:str,payload:dict,vector:list[float]|None=None):
        # Сырые изображения и секреты намеренно не сохраняем.
        if any(k in payload for k in ('image','screenshot','token','account')):raise ValueError('Приватные данные не записываются')
        self.db.execute('INSERT INTO events(ts,game,kind,payload,vector) VALUES (?,?,?,?,?)',
                        (time.time(),game,kind,json.dumps(payload,ensure_ascii=False),json.dumps(vector) if vector else None))
        self.db.commit()
    def recent(self,game:str,limit:int=10):
        rows=self.db.execute('SELECT kind,payload FROM events WHERE game=? ORDER BY id DESC LIMIT ?', (game,limit)).fetchall()
        return [{'kind':k,'payload':json.loads(p)} for k,p in rows]
    def search(self,game:str,vector:list[float],limit:int=5):
        # Точный поиск по маленькой истории без недоступных ARM wheels.
        rows=self.db.execute('SELECT kind,payload,vector FROM events WHERE game=? AND vector IS NOT NULL',(game,)).fetchall()
        result=[]
        qlen=math.sqrt(sum(a*a for a in vector)) or 1.
        for k,p,v in rows:
            other=json.loads(v)
            if len(other)!=len(vector):continue
            denom=(math.sqrt(sum(x*x for x in other)) or 1.)*qlen
            score=sum(a*b for a,b in zip(vector,other))/denom
            result.append((score,{'kind':k,'payload':json.loads(p)}))
        return [r for _,r in sorted(result,key=lambda x:x[0],reverse=True)[:limit]]
    def close(self):self.db.close()
