"""Адаптер к неизменённому Level 6 PC GameAgent, сохранённому внутри Level 8."""
from __future__ import annotations
import importlib
import sys
from pathlib import Path


def legacy_agent(root: str | Path):
    path = (Path(root) / 'legacy_level8' / 'legacy_level6').resolve()
    if not (path / 'game_agent' / 'agent.py').is_file():
        raise RuntimeError('Legacy GameAgent не найден: старый код не переписан')
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    agent = importlib.import_module('game_agent.agent').GameAgent
    settings = importlib.import_module('game_agent.config').Settings
    return agent, settings
