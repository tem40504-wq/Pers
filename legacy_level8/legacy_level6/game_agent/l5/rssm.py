"""Экспериментальная рекуррентная модель динамики (RSSM-lite).

Не является DreamerV3: нет стохастического латента, KL-loss или actor/critic.
Без обучения и калибровки её нельзя использовать для управления.
PyTorch импортируется ТОЛЬКО при создании модели после разрешения оператора.
"""
from __future__ import annotations

class RecurrentDynamics:
    """Предсказывает последовательность состояний [HP,MP,distance,threat]."""
    def __init__(self, hidden=32):
        import torch
        from torch import nn
        self.torch=torch
        self.net=nn.GRU(input_size=7,hidden_size=hidden,batch_first=True)
        self.head=nn.Sequential(nn.Linear(hidden,4),nn.Sigmoid())
        self.trained=False
        self.validation_mae=None

    def _forward(self,x):
        hidden,_=self.net(x)
        return self.head(hidden)

    def fit(self,x_train,y_train,x_valid,y_valid,epochs=30):
        """Вход [batch,time,7]: 4 метрики + one-hot действие.

        Сначала train/validation split по сессиям, не случайным кадрам.
        Без валидации обученная модель не допускается до принятия решений.
        """
        import numpy as np
        torch=self.torch
        x=torch.as_tensor(x_train,dtype=torch.float32)
        y=torch.as_tensor(y_train,dtype=torch.float32)
        vx=torch.as_tensor(x_valid,dtype=torch.float32)
        vy=torch.as_tensor(y_valid,dtype=torch.float32)
        if x.ndim!=3 or x.shape[-1]!=7 or y.shape!=(*x.shape[:2],4):
            raise ValueError("Ожидается [batch,time,7] -> [batch,time,4]")
        if len(x)<20 or len(vx)<5:
            raise ValueError("Недостаточно независимых обучающих эпизодов")
        opt=torch.optim.Adam(list(self.net.parameters())+list(self.head.parameters()),lr=1e-3)
        loss=torch.nn.SmoothL1Loss()
        for _ in range(min(epochs,200)):
            opt.zero_grad()
            pred=self._forward(x)
            err=loss(pred,y)
            err.backward()
            opt.step()
        with torch.no_grad():
            mae=float(torch.mean(torch.abs(self._forward(vx)-vy)))
        self.validation_mae=mae
        # Это порог для пилотных тестов; не гарантия качества в новой игре.
        self.trained=mae<.08
        return mae

    def predict_sequence(self,features):
        if not self.trained:
            raise RuntimeError("RSSM-lite не прошла валидацию")
        x=self.torch.as_tensor(features,dtype=self.torch.float32)
        if x.ndim!=3 or x.shape[-1]!=7:
            raise ValueError("Вход [batch,time,7]")
        with self.torch.no_grad():return self._forward(x).numpy()
