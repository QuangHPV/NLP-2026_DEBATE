"""Debate evaluation system for student agents."""

from .api import BaseAgent, StudentAPI, UsageStats
from .engine import DebateMatch, DebateMaterial, DebateTurn, judger
from .loader import AgentLoadResult, discover_student_agents

__all__ = [
    "AgentLoadResult",
    "BaseAgent",
    "DebateMatch",
    "DebateMaterial",
    "DebateTurn",
    "StudentAPI",
    "UsageStats",
    "discover_student_agents",
    "judger",
]
