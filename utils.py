from __future__ import annotations

from openai import OpenAI


API_URL = "https://llmapi.paratera.com"
BASE_URL = f"{API_URL}/v1/"

client = OpenAI(
    api_key="sk-dCZnQbhuxRELg8bvRyeQOw",
    base_url=BASE_URL,
)

student_model = "DeepSeek-V4-Flash"
judger_model = "DeepSeek-V4-Pro"
material_model = "DeepSeek-V4-Pro"


def chat(messages: list[dict[str, str]], model: str) -> dict:
    """Centralized chat completion entrypoint for the whole project."""
    return client.chat.completions.create(messages=messages, model=model).model_dump()


def extract_text(response: dict) -> str:
    choices = response.get("choices", [])
    if not choices:
        raise ValueError("API response does not contain choices.")

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        text_parts = [item.get("text", "") for item in content if item.get("type") == "text"]
        return "".join(text_parts).strip()
    return str(content).strip()


def chat_text(messages: list[dict[str, str]], model: str) -> str:
    response = chat(messages=messages, model=model)
    return extract_text(response)


def chat_text_with_usage(messages: list[dict[str, str]], model: str) -> tuple[str, dict]:
    response = chat(messages=messages, model=model)
    return extract_text(response), response.get("usage") or {}


def student_chat(messages: list[dict[str, str]]) -> str:
    return chat_text(messages=messages, model=student_model)


def student_chat_with_usage(messages: list[dict[str, str]]) -> tuple[str, dict]:
    return chat_text_with_usage(messages=messages, model=student_model)


def judge_chat(messages: list[dict[str, str]]) -> str:
    return chat_text(messages=messages, model=judger_model)


def material_chat(messages: list[dict[str, str]]) -> str:
    return chat_text(messages=messages, model=material_model)


if __name__ == "__main__":
    demo_messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant.",
        },
        {
            "role": "user",
            "content": "What are some famous landmarks in Rome?",
        },
    ]

    print(student_chat(demo_messages))
