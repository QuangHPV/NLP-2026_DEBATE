from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from typing import Any

from utils import student_chat


ChatTemplate = list[dict[str, str]]


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
    """Utility methods exposed to students during evaluation."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.usage = UsageStats()

    def chat(
        self,
        messages: ChatTemplate | None = None,
        *,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        history: ChatTemplate | None = None,
    ) -> str:
        template = self._build_messages(
            messages=messages,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            history=history,
        )

        self.usage.chat_calls += 1
        self.usage.prompt_chars += _count_chars(template)
        response = student_chat(template)
        self.usage.response_chars += len(response)
        return response

    def _build_messages(
        self,
        messages: ChatTemplate | None = None,
        *,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        history: ChatTemplate | None = None,
    ) -> ChatTemplate:
        if messages is not None:
            template = deepcopy(messages)
        else:
            template = deepcopy(history or [])
            if system_prompt is not None and not any(
                message.get("role") == "system" for message in template
            ):
                template.insert(0, {"role": "system", "content": system_prompt})
            if user_prompt is not None:
                template.append({"role": "user", "content": user_prompt})

        if not template:
            raise ValueError("chat() requires either messages or history/user_prompt content.")
        return template

    # Backward-compatible helper. It does not call the API.
    def foward(
        self,
        chat_template: ChatTemplate,
        content: str,
        role: str = "user",
    ) -> ChatTemplate:
        template = deepcopy(chat_template)
        template.append({"role": role, "content": content})
        return template

    def forward(
        self,
        chat_template: ChatTemplate,
        content: str,
        role: str = "user",
    ) -> ChatTemplate:
        return self.foward(chat_template, content=content, role=role)

    # Backward-compatible helper. The actual model call still goes through utils.py.
    def generate(self, chat_template: ChatTemplate) -> str:
        return self.chat(chat_template)

    def usage_json(self) -> str:
        return json.dumps(self.usage.to_dict(), ensure_ascii=False, indent=2)


class BaseAgent:
    """Students should inherit from this class and implement argue()."""

    def __init__(self, api: StudentAPI, side: str, topic: str, material: str):
        self.api = api
        self.side = side
        self.topic = topic
        self.material = material

    def chat(
        self,
        messages: ChatTemplate | None = None,
        *,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        history: ChatTemplate | None = None,
    ) -> str:
        return self.api.chat(
            messages=messages,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            history=history,
        )

    def foward(
        self,
        chat_template: ChatTemplate,
        content: str,
        role: str = "user",
    ) -> ChatTemplate:
        return self.api.foward(chat_template, content=content, role=role)

    def forward(
        self,
        chat_template: ChatTemplate,
        content: str,
        role: str = "user",
    ) -> ChatTemplate:
        return self.api.forward(chat_template, content=content, role=role)

    def generate(self, chat_template: ChatTemplate) -> str:
        return self.api.generate(chat_template)

    def argue(self, chat_history: ChatTemplate) -> str:
        raise NotImplementedError("Students must implement argue(chat_history).")

    def usage(self) -> dict[str, Any]:
        return self.api.usage.to_dict()
