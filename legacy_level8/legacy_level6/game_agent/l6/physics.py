"""Приближённый физический прогноз для калиброванной ортографической сцены.

Из одного bbox невозможно восстановить 3D геометрию и скорость без калибровки.
Не применяется для принятия игровых действий без независимой проверки.
"""
from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Trajectory:
    points_3d: tuple[tuple[float,float,float], ...]
    landing_world: tuple[float,float]
    landing_screen_px: tuple[float,float]
    flight_seconds: float
    aoe_screen_radius_px: float
    calibrated: bool


class PhysicsWorldModel:
    def __init__(self, base_world_model=None, gravity=9.81):
        self.base_world_model=base_world_model
        self.gravity=float(gravity)
        if not 0 < self.gravity <= 50:
            raise ValueError('Некорректная гравитация')

    def predict_trajectory(self, object_bbox, velocity_vector, *,
                           pixels_per_meter:float, initial_height_m:float,
                           aoe_radius_m=0.0, dt=.02, max_seconds=10.0) -> Trajectory:
        """`velocity_vector` — vx,vy,vz в м/с в откалиброванной системе игры.

        Предполагается проекция сверху XY без перспективы: для 3D камер
        потребуется отдельная camera projection. Рикошеты — отдельная модель.
        """
        if len(object_bbox)!=4 or len(velocity_vector)!=3:
            raise ValueError('Неверные входные размеры')
        vals=list(object_bbox)+list(velocity_vector)+[pixels_per_meter,initial_height_m,aoe_radius_m,dt,max_seconds]
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in vals):
            raise ValueError('Нужна калибровка и конечные числа')
        if pixels_per_meter <= 0 or initial_height_m <= 0 or dt<=0 or max_seconds<=0 or aoe_radius_m<0:
            raise ValueError('Физическая калибровка отсутствует или неверна')
        x1,y1,x2,y2=object_bbox
        if x2<=x1 or y2<=y1:
            raise ValueError('Неверный bbox')
        vx,vy,vz=velocity_vector
        x0=(x1+x2)/2/pixels_per_meter
        y0=(y1+y2)/2/pixels_per_meter
        # Первый момент контакта с плоскостью z=0.
        t=(vz+math.sqrt(vz*vz+2*self.gravity*initial_height_m))/self.gravity
        if t>max_seconds:
            raise ValueError('Траектория выходит за горизонт прогноза')
        n=min(2000,math.ceil(t/dt))
        pts=[]
        for i in range(n+1):
            now=t*i/n
            pts.append((x0+vx*now,y0+vy*now,
                        max(0.,initial_height_m+vz*now-.5*self.gravity*now**2)))
        end=pts[-1]
        return Trajectory(tuple(pts),(end[0],end[1]),
                          (end[0]*pixels_per_meter,end[1]*pixels_per_meter),
                          t,aoe_radius_m*pixels_per_meter,True)

    @staticmethod
    def ricochet_velocity(velocity_vector, surface_normal, restitution=.65):
        """Отражение 3D скорости от плоской поверхности.

        Формула v_out = v_in -(1+e)*(v_in·n)*n. Поверхность и коэффициент
        отражения требуют калибровки; дополнительные столкновения не считаем.
        """
        if len(velocity_vector)!=3 or len(surface_normal)!=3:
            raise ValueError('Нужны три компоненты скорости и нормали')
        data=tuple(velocity_vector)+tuple(surface_normal)+(restitution,)
        if not all(type(z) in (float,int) and math.isfinite(z) for z in data) or not 0<=restitution<=1:
            raise ValueError('Некорректные параметры отражения')
        length=math.sqrt(sum(float(z)**2 for z in surface_normal))
        if length<1e-8:raise ValueError('Нулевая нормаль')
        normal=tuple(z/length for z in surface_normal)
        projection=sum(v*n for v,n in zip(velocity_vector,normal))
        # Если объект улетает от плоскости, дополнительного отражения нет.
        if projection>=0:return tuple(float(z) for z in velocity_vector)
        return tuple(v-(1+restitution)*projection*n for v,n in zip(velocity_vector,normal))
