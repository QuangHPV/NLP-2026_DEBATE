"""Debate evaluation system for student agents."""

from .api import (
    DebateHistory,
    ReadonlyDebateMaterial,
    ReadonlyDebateTurn,
    StudentAPI,
    UsageStats,
    chat,
)
from .engine import DebateMatch, DebateMaterial, DebateTurn, judger
from .loader import AgentLoadResult, discover_student_agents, load_student_agent

__all__ = [
    "AgentLoadResult",
    "DebateHistory",
    "DebateMatch",
    "DebateMaterial",
    "DebateTurn",
    "ReadonlyDebateMaterial",
    "ReadonlyDebateTurn",
    "StudentAPI",
    "UsageStats",
    "chat",
    "discover_student_agents",
    "judger",
    "load_student_agent",
]
