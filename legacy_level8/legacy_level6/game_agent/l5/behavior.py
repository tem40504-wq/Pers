"""Offline-моделирование пользовательских жестов для UX-тестов.

Не гарантирует сходства с человеком и не предназначено для обхода античита.
На реальный Android передача траектории идёт только через старый Safety Gate.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import random

@dataclass(frozen=True)
class GesturePoint:
    x: int
    y: int
    pause_ms: int

class HumanBehaviorGenerator:
    """По умолчанию плавная интерполяция; GAN обучается только офлайн явно."""
    def __init__(self, seed=1234, points=24):
        self.rng = random.Random(seed)
        self.points = points
        self.generator = None
        self._torch = None

    def train_gan(self, demonstrations: list[list[tuple[float,float]]], epochs=50):
        """Обучить небольшой GAN на добровольно записанных нормализованных жестах.

        Не скачиваем PyTorch или датасеты: torch должен быть заранее разрешён.
        Гарантий реалистичности нет, модель требует валидации.
        """
        if len(demonstrations) < 20:
            raise ValueError("Для GAN требуется хотя бы 20 размеченных жестов")
        import torch
        from torch import nn
        import numpy as np
        size = self.points
        def resample(seq):
            pts = np.asarray(seq,dtype=np.float32)
            if pts.ndim!=2 or pts.shape[1]!=2 or len(pts)<2:
                raise ValueError("Жест должен состоять из (x,y)")
            times = np.linspace(0,1,len(pts))
            t = np.linspace(0,1,size)
            p = np.column_stack([np.interp(t,times,pts[:,j]) for j in (0,1)])
            return p - ((1-t[:,None])*p[0] + t[:,None]*p[-1])
        data=torch.tensor(np.stack([resample(x) for x in demonstrations]),dtype=torch.float32)
        data = torch.clamp(data, -.25,.25).reshape(len(data),-1)
        generator=nn.Sequential(nn.Linear(16,64),nn.ReLU(),nn.Linear(64,128),nn.ReLU(),nn.Linear(128,size*2),nn.Tanh())
        critic=nn.Sequential(nn.Linear(size*2,128),nn.LeakyReLU(.2),nn.Linear(128,64),nn.LeakyReLU(.2),nn.Linear(64,1),nn.Sigmoid())
        opt_g=torch.optim.Adam(generator.parameters(),lr=.0002)
        opt_d=torch.optim.Adam(critic.parameters(),lr=.0002)
        loss=nn.BCELoss()
        for _ in range(min(epochs,200)):
            for real in data.split(16):
                noise=torch.randn(len(real),16)
                fake=.25*generator(noise)
                opt_d.zero_grad()
                ld=loss(critic(real),torch.ones(len(real),1))+loss(critic(fake.detach()),torch.zeros(len(real),1))
                ld.backward(); opt_d.step()
                opt_g.zero_grad()
                lg=loss(critic(fake),torch.ones(len(real),1))
                lg.backward(); opt_g.step()
        generator.eval()
        self.generator=generator
        self._torch=torch
        return True

    def generate_human_swipe(self, start, end) -> list[GesturePoint]:
        """Получить ограниченную траекторию; без прямого вызова input/swipe."""
        x1,y1=start; x2,y2=end
        n=self.points
        d=math.hypot(x2-x1,y2-y1)
        offsets=None
        if self.generator is not None:
            with self._torch.no_grad():
                offsets=(.25*self.generator(self._torch.randn(1,16))).reshape(n,2).numpy()
        points=[]
        drift=0.
        for i in range(n):
            t=i/(n-1)
            eased=t*t*(3-2*t)
            # Плавный низкочастотный шум, не выходящий за небольшой коридор.
            drift=max(-1.,min(1.,.82*drift+self.rng.uniform(-.25,.25)))
            dx,dy=(offsets[i] if offsets is not None else (0.,0.))
            fade=4*t*(1-t)
            x=x1+eased*(x2-x1)+fade*(dx*d + drift*min(3.,d*.015))
            y=y1+eased*(y2-y1)+fade*(dy*d)
            pause=0 if i in (0,n-1) else self.rng.randint(8,25)
            points.append(GesturePoint(round(x),round(y),pause))
        points[0]=GesturePoint(int(x1),int(y1),0)
        points[-1]=GesturePoint(int(x2),int(y2),0)
        return points
