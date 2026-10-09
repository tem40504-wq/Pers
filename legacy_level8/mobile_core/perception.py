"""Слой распознавания с адаптерами: YOLO TFLite/ML Kit/YAMNet вызываются в APK."""
from __future__ import annotations
from .contracts import Observation,Detection

class MobilePerception:
    def __init__(self, detector=None, ocr=None, audio=None, vlm=None):
        self.detector=detector;self.ocr=ocr;self.audio=audio;self.vlm=vlm
    def observe(self,frame:bytes, metadata:dict|None=None,slow=False)->Observation:
        meta=metadata or {}
        obs=Observation(width=int(meta.get('width',1080)),height=int(meta.get('height',2400)),
                        hp=meta.get('hp'),mp=meta.get('mp'),thermal_c=meta.get('thermal_c'),
                        scene=str(meta.get('scene','unknown')))
        # Модель подключается только если её веса уже разрешены и установлены.
        if self.detector:
            for obj in self.detector(frame):
                obs.detections.append(Detection(str(obj['label']),float(obj['confidence']),tuple(obj['bbox'])))
        if slow:obs.texts=list(self.ocr(frame)) if self.ocr else list(meta.get('texts',[]))
        if slow and self.audio:obs.audio_events=list(self.audio())
        if slow and self.vlm and obs.scene=='unknown':
            guess=self.vlm(frame)
            if isinstance(guess,dict) and float(guess.get('confidence',0))>=.7:
                obs.scene=str(guess.get('scene','unknown'))
        obs.screenshot_jpeg=frame
        return obs
