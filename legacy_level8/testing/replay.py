"""Снимки и телеметрия для проверки без реального ввода. Ротация по байтам."""
from __future__ import annotations
from pathlib import Path
from collections import deque
import json,sqlite3,hashlib,time,os,threading

class ReplayBuffer:
    def __init__(self,root,max_bytes=50*1024**3,interval=.5,blackbox_size=100):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.frames=self.root/'frames';self.frames.mkdir(exist_ok=True)
        self.db=sqlite3.connect(self.root/'replay.db',check_same_thread=False)
        self.lock=threading.RLock()
        self.max_bytes=int(max_bytes);self.interval=float(interval)
        self.blackbox=deque(maxlen=blackbox_size)
        # Последние JPEG остаются в кольце памяти даже при ротации диска.
        self.blackbox_frames=deque(maxlen=blackbox_size)
        self.last_frame_ts=-1e30
        self.db.execute('''CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
            frame TEXT NOT NULL, state TEXT NOT NULL, action TEXT NOT NULL,
            outcome TEXT NOT NULL, size INTEGER NOT NULL)''')
        self.db.commit()

    def append(self,*,state:dict,action:dict,outcome:str,frame_jpeg:bytes=b'',ts=None,private=False):
        ts=time.monotonic() if ts is None else float(ts)
        if not isinstance(frame_jpeg,bytes):raise TypeError('jpeg bytes expected')
        with self.lock:
            # Храним действия на каждом шаге, кадр не чаще 2 FPS.
            store_frame=bool(frame_jpeg and not private and ts-self.last_frame_ts>=self.interval)
            filename='';size=0
            if store_frame:
                if not frame_jpeg.startswith(b'\xff\xd8'):
                    raise ValueError('Для кадров нужны сжатые JPEG-байты')
                digest=hashlib.sha256(frame_jpeg).hexdigest()
                filename=f'{int(ts*1000)}_{digest[:12]}.jpg'
                (self.frames/filename).write_bytes(frame_jpeg)
                size=len(frame_jpeg);self.last_frame_ts=ts
            safe_state=json.dumps(state,ensure_ascii=False,sort_keys=True)
            safe_action=json.dumps(action,ensure_ascii=False,sort_keys=True)
            cur=self.db.execute('INSERT INTO events(ts,frame,state,action,outcome,size) VALUES(?,?,?,?,?,?)',
                                (ts,filename,safe_state,safe_action,outcome,size))
            self.db.commit()
            row={'id':cur.lastrowid,'ts':ts,'frame':filename,'state':state,'action':action,'outcome':outcome}
            self.blackbox.append(row)
            if store_frame:self.blackbox_frames.append((filename,frame_jpeg))
            self.rotate()
            return row

    def events(self,limit=100):
        with self.lock:
            rows=self.db.execute('SELECT id,ts,frame,state,action,outcome FROM events ORDER BY id DESC LIMIT ?',
                                 (max(1,int(limit)),)).fetchall()
            return [dict(id=r[0],ts=r[1],frame=r[2],state=json.loads(r[3]),
                         action=json.loads(r[4]),outcome=r[5]) for r in reversed(rows)]

    def rotate(self):
        # Удаляем самые старые кадры до выполнения лимита.
        rows=self.db.execute('SELECT id,frame,size FROM events ORDER BY id ASC').fetchall()
        total=sum(r[2] for r in rows)
        for row_id,filename,size in rows:
            if total<=self.max_bytes:break
            if filename:(self.frames/filename).unlink(missing_ok=True)
            self.db.execute('DELETE FROM events WHERE id=?',(row_id,))
            total-=size
        self.db.commit()

    def freeze_blackbox(self,folder):
        dest=Path(folder);dest.mkdir(parents=True,exist_ok=True)
        with self.lock:
            rows=list(self.blackbox)
            (dest/'blackbox.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            cached=dict(self.blackbox_frames)
            for row in rows:
                if row['frame']:
                    file=self.frames/row['frame']
                    if row['frame'] in cached:
                        (dest/row['frame']).write_bytes(cached[row['frame']])
                    elif file.exists():
                        (dest/row['frame']).write_bytes(file.read_bytes())
        return dest

    def close(self):
        with self.lock:self.db.close()
