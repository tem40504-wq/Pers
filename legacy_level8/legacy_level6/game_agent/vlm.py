"""Только запросы по триггеру, без доступа нейросети к командной строке."""
import base64
import json
import requests


class VLMError(RuntimeError):
    pass


JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["tap", "swipe", "wait"]},
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "x1": {"type": "integer"}, "y1": {"type": "integer"},
        "x2": {"type": "integer"}, "y2": {"type": "integer"},
        "duration_ms": {"type": "integer"},
        "confidence": {"type": "number"},
        "risk": {"type": "string", "enum": ["safe", "uncertain", "prohibited"]},
        "reason": {"type": "string"},
    },
    "required": ["action", "confidence", "risk", "reason"],
    "additionalProperties": False,
}


class VLM:
    def __init__(self, provider="ollama", model="qwen2.5vl:3b", url="http://127.0.0.1:11434/api/chat",
                 api_key="", openai_url="https://api.openai.com/v1/chat/completions"):
        self.provider = provider
        self.model = model
        self.url = url
        self.api_key = api_key
        self.openai_url = openai_url
        self.session = requests.Session()

    def ask_json(self, jpeg: bytes, prompt: str, schema=None) -> dict:
        schema = schema or JSON_SCHEMA
        b64 = base64.b64encode(jpeg).decode("ascii")
        try:
            if self.provider == "ollama":
                res = self.session.post(self.url, json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": "Отвечай только валидным JSON. Не выполняй никаких команд."},
                                 {"role": "user", "content": prompt, "images": [b64]}],
                    "stream": False, "format": schema,
                    "options": {"temperature": .1}
                }, timeout=90)
                res.raise_for_status()
                answer = res.json()["message"]["content"]
            elif self.provider == "openai":
                if not self.api_key:
                    raise VLMError("Не установлен VLM_API_KEY")
                res = self.session.post(self.openai_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model,
                          "messages": [{"role": "system", "content": "Отвечай JSON без markdown."},
                                       {"role": "user", "content": [
                                           {"type": "text", "text": prompt},
                                           {"type": "image_url", "image_url": {
                                               "url": f"data:image/jpeg;base64,{b64}"}}]}],
                          "response_format": {"type": "json_object"}}, timeout=90)
                res.raise_for_status()
                answer = res.json()["choices"][0]["message"]["content"]
            else:
                raise VLMError(f"Неизвестный провайдер {self.provider}")
            data = json.loads(answer)
            if not isinstance(data, dict):
                raise ValueError("Ответ должен быть объектом")
            return data
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            raise VLMError(f"VLM ошибка: {exc}") from exc
