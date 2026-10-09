"""Аудиособытия: источник PCM внедряется извне, без скрытого захвата.

Прямого универсального ADB API для захвата внутреннего аудио игры нет.
Звуковой вход: разрешённый оператором loopback/микрофон ПК либо WAV.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from threading import Lock
import time

@dataclass(frozen=True)
class AudioEvent:
    kind: str
    confidence: float
    timestamp: float
    source: str = "audio"

class AudioPerception:
    """Классификатор принимает моно PCM float32 16 kHz и возвращает события.

    Никаких голосовых команд без отдельного распознавателя и проверки прав.
    """
    ALLOWED = frozenset({"enemy_attack", "low_hp_warning", "victory", "level_up"})

    def __init__(self, classifier=None, threshold=0.82, capacity=64):
        self.classifier = classifier
        self.threshold = threshold
        self.events = deque(maxlen=capacity)
        self.lock = Lock()
        self.last_emit = {}

    def process(self, samples, sample_rate: int = 16000, now=None):
        now = time.monotonic() if now is None else now
        if self.classifier is None:
            return []  # Без модели не угадываем тип события.
        if sample_rate != 16000:
            raise ValueError("Нужен mono PCM 16 kHz; ресемплинг делается источником")
        import numpy as np
        pcm = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not (1600 <= len(pcm) <= 16000 * 10) or not np.all(np.isfinite(pcm)):
            raise ValueError("Некорректный PCM-буфер")
        if np.max(np.abs(pcm)) > 1.05:
            raise ValueError("PCM вне диапазона [-1;1]")
        scores = self.classifier.classify(pcm)  # dict: event_name -> confidence
        found = []
        for name, score in scores.items():
            if name not in self.ALLOWED or not isinstance(score, (int,float)):
                continue
            if score >= self.threshold and now - self.last_emit.get(name, -1e10) >= .75:
                event = AudioEvent(name, float(score), now)
                self.last_emit[name] = now
                found.append(event)
        with self.lock:
            self.events.extend(found)
        return found

    def drain(self, now=None, ttl=1.5) -> list[AudioEvent]:
        now = time.monotonic() if now is None else now
        with self.lock:
            all_events = list(self.events)
            self.events.clear()
        return [e for e in all_events if 0 <= now-e.timestamp <= ttl]

class TFLiteYAMNetAdapter:
    """Инференс локального подготовленного YAMNet TFLite.

    Требуется предварительно проверить конкретный экспорт и class-map:
    стандартные классы YAMNet НЕ совпадают с игровыми enemy_attack/victory.
    """
    def __init__(self, model_path, class_map, interpreter_cls=None):
        import numpy as np
        if interpreter_cls is None:
            from tflite_runtime.interpreter import Interpreter as interpreter_cls
        self.np = np
        self.interpreter = interpreter_cls(model_path=str(model_path))
        self.interpreter.allocate_tensors()
        ins, outs = self.interpreter.get_input_details(), self.interpreter.get_output_details()
        if len(ins) != 1 or not outs:
            raise ValueError("Ожидается проверенный одно-входный TFLite экспорт")
        self.input, self.output = ins[0], outs[0]
        if self.input["dtype"] != np.float32:
            raise ValueError("TFLite-вход должен принимать float32 PCM")
        self.class_map = {str(k):int(v) for k,v in class_map.items()}
        if set(self.class_map)-AudioPerception.ALLOWED:
            raise ValueError("Неизвестные игровые категории")

    def classify(self, pcm):
        import numpy as np
        x = np.asarray(pcm,dtype=np.float32)
        shape = list(self.input["shape"])
        # Некоторые экспорты получают waveform [N], другие [1,N].
        if len(shape) == 1:
            shape = [len(x)]
            data = x
        elif len(shape) == 2 and shape[0] in (1,-1):
            shape = [1,len(x)]
            data = x[None,:]
        else:
            raise ValueError("Экспорт не принимает сырую waveform, нужна модельная обёртка")
        self.interpreter.resize_tensor_input(self.input["index"],shape,strict=False)
        self.interpreter.allocate_tensors()
        self.interpreter.set_tensor(self.input["index"],data)
        self.interpreter.invoke()
        output = np.asarray(self.interpreter.get_tensor(self.output["index"]),dtype=float)
        # Обычно выход YAMNet имеет размер [frames, classes].
        if output.ndim == 3:
            output = output.reshape(-1,output.shape[-1])
        if output.ndim == 1:
            output = output[None,:]
        if output.ndim != 2:
            raise ValueError("Неизвестная форма output YAMNet")
        return {name:float(output[:,idx].mean()) for name,idx in self.class_map.items()
                if 0 <= idx < output.shape[1]}

class ApprovedAudioInput:
    """Опциональный PCM источник ПК после явного Y через PermissionGate.

    Передайте loopback-устройство вручную. Эта обёртка не выбирает микрофон
    и не подменяет аудиозахват смартфона автоматически.
    """
    def __init__(self, device_id: int, sample_rate=16000):
        self.device_id = device_id
        self.rate = sample_rate
        self.stream = None

    def start(self, callback):
        import sounddevice as sd  # Только после preflight / Y
        if self.device_id is None:
            raise ValueError("Оператор обязан выбрать конкретное аудиоустройство")
        def receive(indata, frames, time_info, status):
            if not status:
                callback(indata[:,0].copy(),self.rate)
        self.stream = sd.InputStream(device=self.device_id, channels=1,
                                     samplerate=self.rate, blocksize=self.rate,
                                     dtype='float32',callback=receive)
        self.stream.start()

    def close(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
