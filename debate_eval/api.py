from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from typing import Iterator, Literal

from utils import student_chat_with_usage


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
    prompt_tokens: int = 0
    response_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class TurnTokenLimitExceeded(BaseException):
    """Raised when a student agent exceeds its per-turn token budget."""


def _count_chars(chat_template: ChatTemplate) -> int:
    total = 0
    for message in chat_template:
        total += len(message.get("role", ""))
        total += len(message.get("content", ""))
    return total


def _estimate_tokens_from_chars(char_count: int) -> int:
    # Conservative fallback when the API provider does not return token usage.
    return max(1, (char_count + 3) // 4)


def _extract_token_usage(
    usage: dict,
    prompt_chars: int,
    response_chars: int,
) -> tuple[int, int, int]:
    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
    response_tokens = (
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("response_tokens")
    )
    total_tokens = usage.get("total_tokens")

    if prompt_tokens is None:
        prompt_tokens = _estimate_tokens_from_chars(prompt_chars)
    if response_tokens is None:
        response_tokens = _estimate_tokens_from_chars(response_chars)
    if total_tokens is None:
        total_tokens = int(prompt_tokens) + int(response_tokens)

    return int(prompt_tokens), int(response_tokens), int(total_tokens)


class StudentAPI:
    """Per-agent runtime used internally by the evaluator."""

    def __init__(self, agent_name: str, turn_token_limit: int | None = None):
        self.agent_name = agent_name
        self.turn_token_limit = turn_token_limit
        self.usage = UsageStats()
        self._turn_tokens_used = 0
        self._turn_token_limit_exceeded = False

    @contextmanager
    def activate(self) -> Iterator[None]:
        self._turn_tokens_used = 0
        self._turn_token_limit_exceeded = False
        token = _ACTIVE_API.set(self)
        try:
            yield
        finally:
            _ACTIVE_API.reset(token)

    @property
    def turn_token_limit_exceeded(self) -> bool:
        return self._turn_token_limit_exceeded

    def chat(self, messages: ChatTemplate) -> str:
        template = deepcopy(messages)
        if not template:
            raise ValueError("chat() requires at least one message.")

        prompt_chars = _count_chars(template)
        estimated_prompt_tokens = _estimate_tokens_from_chars(prompt_chars)
        if (
            self.turn_token_limit is not None
            and self._turn_tokens_used + estimated_prompt_tokens > self.turn_token_limit
        ):
            self._turn_token_limit_exceeded = True
            raise TurnTokenLimitExceeded(
                f"{self.agent_name} exceeded the per-turn token limit before the next chat call."
            )

        response, token_usage = student_chat_with_usage(template)
        response_chars = len(response)
        prompt_tokens, response_tokens, total_tokens = _extract_token_usage(
            token_usage,
            prompt_chars,
            response_chars,
        )

        self.usage.chat_calls += 1
        self.usage.prompt_chars += prompt_chars
        self.usage.response_chars += response_chars
        self.usage.prompt_tokens += prompt_tokens
        self.usage.response_tokens += response_tokens
        self.usage.total_tokens += total_tokens
        self._turn_tokens_used += total_tokens

        if (
            self.turn_token_limit is not None
            and self._turn_tokens_used > self.turn_token_limit
        ):
            self._turn_token_limit_exceeded = True
            raise TurnTokenLimitExceeded(
                f"{self.agent_name} exceeded the per-turn token limit after a chat call."
            )

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
    """Call the student model with the provided chat template.

    `role` here is only for the LLM API layer (`system` / `user` / `assistant`).
    Do not use message roles to represent debate sides, turns, or speakers.
    Debate history should be passed inside `content` as formatted plain text.
    """
    return _require_active_api().chat(messages)
