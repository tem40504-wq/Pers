"""Моделирование разнообразия жестов В ОФЛАЙН-ТЕСТАХ, не обход античита.

Не применяйте намеренные промахи/двойные нажатия к реальной игре:
они способны потратить ресурсы, выбрать покупку или изменить настройки.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import random

@dataclass(frozen=True)
class GesturePreview:
    x: int
    y: int
    delay_s: float
    missed_center: bool = False
    double_tap: bool = False

class HumanMimicry:
    def __init__(self, mean_delay=.35, seed=None, qa_only=True):
        self.mean_delay = float(mean_delay)
        if self.mean_delay <= 0: raise ValueError('mean_delay должен быть >0')
        self.rng = random.Random(seed)
        self.qa_only = qa_only

    def delay(self) -> float:
        # Отклонение ~30% от среднего; ограничиваем крайние значения.
        return min(self.mean_delay * 1.9,
                   max(self.mean_delay * .1, self.rng.gauss(self.mean_delay, self.mean_delay * .30)))

    def preview_tap(self, bbox: tuple[int, int, int, int], *,
                    offline_test: bool = False) -> GesturePreview:
        """Моделируем 3–5% промахов, 2% двойных тапов в QA-превью.

        Этот метод НЕ отправляет события Android.
        """
        x1, y1, x2, y2 = bbox
        if x1 >= x2 or y1 >= y2: raise ValueError('Пустой bbox')
        cx, cy = (x1+x2)/2, (y1+y2)/2
        if not offline_test:
            # Действия не изменяются без разрешённого тестового режима.
            return GesturePreview(round(cx), round(cy), self.delay())
        miss = self.rng.random() < .04
        # Промах означает смещение ОТ ЦЕНТРА, но за границы bbox не выходим.
        sigma = min(8.0, (x2-x1)/8, (y2-y1)/8)
        x = cx + self.rng.gauss(0, sigma)
        y = cy + self.rng.gauss(0, sigma)
        if miss:
            x = cx + (x2-x1)*(.33 if self.rng.random()<.5 else -.33)
            y = cy + (y2-y1)*(.33 if self.rng.random()<.5 else -.33)
        return GesturePreview(
            max(x1, min(x2-1, round(x))), max(y1, min(y2-1, round(y))),
            self.delay(), miss, self.rng.random() < .02)

    def swipe_preview(self, start: tuple[int, int], end: tuple[int, int],
                      points: int = 20) -> list[tuple[int, int, float]]:
        """Траектория Безье для тестов интерфейса; не real-time HID-инжектор."""
        if points < 3: raise ValueError('Нужно минимум 3 точки')
        x0,y0=start; x3,y3=end
        dx,dy=x3-x0,y3-y0
        length=math.hypot(dx,dy)
        bend=min(10.,length*.04)
        nx,ny=(-dy/length,dx/length) if length else (0,0)
        offset=self.rng.uniform(-bend,bend)
        p1=(x0+dx*.33+nx*offset,y0+dy*.33+ny*offset)
        p2=(x0+dx*.67-nx*offset,y0+dy*.67-ny*offset)
        duration_ms=self.rng.randint(200,800)
        result=[]
        for i in range(points):
            t=i/(points-1); u=1-t
            x=u**3*x0+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*x3
            y=u**3*y0+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*y3
            # Полезная временная сетка для тестирования распознавания жеста.
            result.append((round(x),round(y),round(t*duration_ms,1)))
        return result

    def microgesture_preview(self,center:tuple[int,int],offline_test:bool=False):
        """Только неисполняемые QA-координаты; не посылаются Android.

        Проверяет, что тестируемый UI устойчив к короткому шуму входных событий.
        """
        if not offline_test:return []
        count=self.rng.randint(2,3)
        x,y=center
        result=[]
        for _ in range(count):
            dx=self.rng.choice((-2,-1,1,2));dy=self.rng.choice((-2,-1,1,2))
            result.append(((x,y),(x+dx,y+dy)))
        return result
