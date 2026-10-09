"""Быстрая адаптация цвета UI по размеченным примерам (не MAML)."""
from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LabeledRegion:
    image: object  # numpy.ndarray BGR (из OpenCV; загружается раньше через preflight)
    bbox: tuple[int,int,int,int]
    label: str


class MetaAdapter:
    """5–10 подтверждённых областей UI -> цветовые прототипы по Lab.

    Не изменяет существующие веса YOLO или Perception L3.
    Для настоящего MAML нужны мета-обученные веса и episodic training.
    """
    def __init__(self):
        self.prototypes = {}
        self.count = 0

    def fit(self, examples: list[LabeledRegion]):
        if not 5 <= len(examples) <= 10:
            raise ValueError("Для адаптации нужны 5–10 размеченных областей")
        import cv2
        import numpy as np
        groups = {}
        for example in examples:
            img = example.image
            if img is None or len(img.shape) != 3:
                raise ValueError("Ожидается изображение BGR")
            h,w = img.shape[:2]
            x1,y1,x2,y2 = example.bbox
            if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                raise ValueError("Некорректная ROI")
            crop = img[y1:y2,x1:x2]
            lab = cv2.cvtColor(crop,cv2.COLOR_BGR2LAB).reshape(-1,3)
            groups.setdefault(example.label,[]).append(np.median(lab,axis=0))
        self.prototypes = {k:np.mean(v,axis=0) for k,v in groups.items()}
        self.count = len(examples)
        return len(self.prototypes)

    def classify(self, image, bbox, threshold=27.):
        if not self.prototypes:
            return None, 0.
        import numpy as np
        import cv2
        x1,y1,x2,y2 = bbox
        crop = image[y1:y2,x1:x2]
        if crop.size == 0:
            return None, 0.
        center = np.median(cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).reshape(-1,3),axis=0)
        label, dist = min(((k,float(np.linalg.norm(center-v))) for k,v in self.prototypes.items()), key=lambda p:p[1])
        return (label, max(0., 1 - dist/max(threshold,1))) if dist <= threshold else (None, 0.)
