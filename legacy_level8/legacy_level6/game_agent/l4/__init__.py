"""Дополнительный уровень 4; старые модули доступны независимо."""
from .temporal import GameStateVector, GameStateExtractor, TemporalPredictor, Prediction
from .local_vlm import LocalVLM, CascadedVLM, OnnxRuntimeAdapter
from .swarm import SwarmBus, SwarmCoordinator
from .dsl import DSLInterpreter, SkillRegistry, DSLParseError

__all__ = ["GameStateVector", "GameStateExtractor", "TemporalPredictor", "Prediction",
           "LocalVLM", "CascadedVLM", "OnnxRuntimeAdapter", "SwarmBus", "SwarmCoordinator",
           "DSLInterpreter", "SkillRegistry", "DSLParseError"]
