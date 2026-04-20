from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from typing import Iterator, Literal

from utils import student_chat


ChatTemplate = list[dict[str, str]]
Side = Literal["affirmative", "negative"]


@dataclass(frozen=True)
class ReadonlyDebateMaterial:
    topic: str
    content: str


@dataclass(frozen=True)
class ReadonlyDebateTurn:
    round_index: int
    side: Side
    speaker: str
    content: str


DebateHistory = tuple[ReadonlyDebateTurn, ...]


@dataclass
class UsageStats:
    chat_calls: int = 0
    prompt_chars: int = 0
    response_chars: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _count_chars(chat_template: ChatTemplate) -> int:
    total = 0
    for message in chat_template:
        total += len(message.get("role", ""))
        total += len(message.get("content", ""))
    return total


class StudentAPI:
    """Per-agent runtime used internally by the evaluator."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.usage = UsageStats()

    @contextmanager
    def activate(self) -> Iterator[None]:
        token = _ACTIVE_API.set(self)
        try:
            yield
        finally:
            _ACTIVE_API.reset(token)

    def chat(self, messages: ChatTemplate) -> str:
        template = deepcopy(messages)
        if not template:
            raise ValueError("chat() requires at least one message.")

        self.usage.chat_calls += 1
        self.usage.prompt_chars += _count_chars(template)
        response = student_chat(template)
        self.usage.response_chars += len(response)
        return response

    def usage_json(self) -> str:
        return json.dumps(self.usage.to_dict(), ensure_ascii=False, indent=2)


_ACTIVE_API: ContextVar[StudentAPI | None] = ContextVar("student_api", default=None)


def _require_active_api() -> StudentAPI:
    api = _ACTIVE_API.get()
    if api is None:
        raise RuntimeError(
            "debate_eval.api.chat() can only be used while the evaluator is invoking speak()."
        )
    return api


def chat(messages: ChatTemplate) -> str:
    """Call the student model with the provided chat template."""
    return _require_active_api().chat(messages)


def forward(
    messages: ChatTemplate,
    content: str,
    role: str = "user",
) -> ChatTemplate:
    """Return a new message list with one extra message appended."""
    template = deepcopy(messages)
    template.append({"role": role, "content": content})
    return template


def generate(messages: ChatTemplate) -> str:
    """Backward-compatible alias of chat()."""
    return chat(messages)
