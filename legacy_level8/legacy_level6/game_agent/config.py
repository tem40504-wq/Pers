"""Параметры работы по умолчанию; реальные нажатия выключены."""
from dataclasses import dataclass
import os


@dataclass
class Settings:
    adb_path: str = os.getenv("ADB_PATH", "adb")
    serial: str | None = os.getenv("ADB_SERIAL") or None
    game_id: str = os.getenv("GAME_ID", "generic")
    user_goal: str = os.getenv("GAME_GOAL", "исследовать интерфейс безопасно")
    worker_period: float = 0.5
    manager_period: float = 10.0
    ocr_period: float = 3.0  # OCR гораздо медленнее кадрового цикла
    vlm_cooldown: float = 12.0
    enable_ocr: bool = False
    enable_yolo: bool = False
    yolo_weights: str | None = None  # Нужны обученные веса по игровым UI, а не COCO
    vlm_provider: str = os.getenv("VLM_PROVIDER", "ollama")
    vlm_model: str = os.getenv("VLM_MODEL", "qwen2.5vl:3b")
    vlm_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
    api_key: str = os.getenv("VLM_API_KEY", "")
    openai_url: str = os.getenv("OPENAI_COMPAT_URL", "https://api.openai.com/v1/chat/completions")
    dry_run: bool = True
    max_steps: int = 20
    confidence_threshold: float = 0.72
    memory_dir: str = "runtime"
    enable_chroma: bool = False
    safe_zones: tuple[tuple[int, int, int, int], ...] = ()  # Явно согласованные области экрана
    explore: bool = False
    max_explore_actions: int = 10
