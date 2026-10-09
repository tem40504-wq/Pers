"""Локальная VLM с приоритетом ONNX (если экспорт полон) или Ollama.
Облачный VLM используется только при низкой уверенности / сбое локальной.
"""
from __future__ import annotations
import math
from typing import Any, Callable
from ..vlm import VLM


class OnnxRuntimeAdapter:
    """Адаптер к ГОТОВОМУ ONNX-экспорту.

    Полноценная Qwen2-VL требует image processor, tokenizer, vision encoder,
    LLM decoder, KV-cache и итеративной генерации. Нельзя считать один
    onnxruntime.InferenceSession готовой Qwen2-VL. `encode_inputs`/`decode_outputs`
    предоставляет экспортированный модельный пакет.
    """
    def __init__(self, model_path: str,
                 encode_inputs: Callable[[bytes, str, Any], dict],
                 decode_outputs: Callable[[list], dict],
                 providers: list[str] | None = None):
        import onnxruntime as ort  # Опциональная зависимость
        self.session = ort.InferenceSession(model_path,
                providers=providers or ["CPUExecutionProvider"])
        self.encode_inputs = encode_inputs
        self.decode_outputs = decode_outputs

    def ask_json(self, jpeg: bytes, prompt: str, schema=None) -> dict:
        feeds = self.encode_inputs(jpeg, prompt, schema)
        valid_names = {i.name for i in self.session.get_inputs()}
        if set(feeds) != valid_names:
            raise ValueError("Несовпадение входов экспортированной ONNX-модели")
        return self.decode_outputs(self.session.run(None, feeds))


DSL_SCHEMA = {
    "type": "object",
    "properties": {
        "dsl": {"type": "string"},
        "confidence": {"type": "number"}
    },
    "required": ["dsl", "confidence"],
    "additionalProperties": False
}


class LocalVLM:
    """Основной локальный источник. По умолчанию настоящий VLM через Ollama.

    Поддерживается инъекция OnnxRuntimeAdapter для готового экспорта.
    """
    def __init__(self, backend=None, model="qwen2.5vl:3b",
                 url="http://127.0.0.1:11434/api/chat"):
        self.backend = backend or VLM("ollama", model, url, "", "")

    def ask_json(self, jpeg: bytes, prompt: str, schema=None) -> dict:
        answer = self.backend.ask_json(jpeg, prompt, schema=schema)
        if not isinstance(answer, dict):
            raise ValueError("Локальная VLM вернула не JSON-объект")
        return answer


class CascadedVLM:
    def __init__(self, local: LocalVLM, cloud=None, legacy=None,
                 threshold=.70, allow_cloud=False):
        self.local, self.cloud, self.legacy = local, cloud, legacy
        self.threshold, self.allow_cloud = threshold, allow_cloud
        self.last_backend = "none"

    @staticmethod
    def _score(ans: dict) -> float:
        score = ans.get("confidence", 0)
        if type(score) not in (int, float) or not math.isfinite(score):
            return 0.
        return max(0., min(1., float(score)))

    def ask_json(self, jpeg: bytes, prompt: str, schema=None) -> dict:
        answer = None
        try:
            answer = self.local.ask_json(jpeg, prompt, schema=schema)
            if self._score(answer) >= self.threshold:
                self.last_backend = "local"
                return answer
        except Exception:
            pass
        # Вынос кадра в облако — ТОЛЬКО после явного включения пользователя.
        if self.allow_cloud and self.cloud is not None:
            try:
                cloud_ans = self.cloud.ask_json(jpeg, prompt, schema=schema)
                if self._score(cloud_ans) >= self.threshold:
                    self.last_backend = "cloud"
                    return cloud_ans
            except Exception:
                pass
        # Старый VLM остаётся резервом, но его выход по-прежнему проверяет DSL.
        if self.legacy is not None:
            try:
                old = self.legacy.ask_json(jpeg, prompt, schema=schema)
                if self._score(old) >= self.threshold:
                    self.last_backend = "legacy"
                    return old
            except Exception:
                pass
        self.last_backend = "insufficient_confidence"
        return {"dsl": "IF False THEN wait()", "confidence": 0.0}
