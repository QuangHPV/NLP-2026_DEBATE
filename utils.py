from __future__ import annotations

from openai import OpenAI


client = OpenAI(
    api_key="REDACTED_API_KEY",
    base_url="https://yeysai.com/v1",
)

student_model = "gpt-4o"
judger_model = "gemini-3.1-pro-preview"
material_model = "gemini-3.1-pro-preview"


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


def student_chat(messages: list[dict[str, str]]) -> str:
    return chat_text(messages=messages, model=student_model)


def judge_chat(messages: list[dict[str, str]]) -> str:
    return chat_text(messages=messages, model=judger_model)


def material_chat(messages: list[dict[str, str]]) -> str:
    return chat_text(messages=messages, model=material_model)


if __name__ == "__main__":
    demo_messages = [
        {
            "role": "system",
            "content": "你是一个专业的AI助手，能够帮助用户解决各种问题。",
        },
        {
            "role": "user",
            "content": "罗马有哪些著名景点？",
        },
    ]

    print(student_chat(demo_messages))
