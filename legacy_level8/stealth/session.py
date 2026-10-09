"""Ресурсные ограничения сеанса и перерывы по выбору оператора.

НЕ позиционируется как имитация живого игрока или средство снижения банов.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import random
import time

@dataclass(frozen=True)
class SessionState:
    allowed: bool
    reason: str
    remaining_s: float

class SessionSimulator:
    def __init__(self, seed=None, sleep_start=2, sleep_end=8,
                 session_minutes=(45,90), break_minutes=(10,30)):
        self.rng=random.Random(seed)
        self.sleep_start=sleep_start; self.sleep_end=sleep_end
        self.session_minutes=session_minutes;self.break_minutes=break_minutes
        self.started_at=None;self.pause_until=0.
        self.limit_seconds=0.

    def begin(self, now=None):
        now = time.monotonic() if now is None else now
        self.started_at=now
        self.limit_seconds=self.rng.uniform(*self.session_minutes)*60

    def check(self, *, monotonic_now=None, local_dt=None)->SessionState:
        now=time.monotonic() if monotonic_now is None else monotonic_now
        local_dt=local_dt or datetime.now().astimezone()
        if self.sleep_start <= local_dt.hour < self.sleep_end:
            return SessionState(False,'quiet_hours',0)
        if now < self.pause_until:
            return SessionState(False,'rest_break',self.pause_until-now)
        if self.started_at is None:self.begin(now)
        elapsed=now-self.started_at
        if elapsed>=self.limit_seconds:
            self.pause_until=now+self.rng.uniform(*self.break_minutes)*60
            self.started_at=None
            return SessionState(False,'session_limit',self.pause_until-now)
        return SessionState(True,'within_limits',max(0,self.limit_seconds-elapsed))
