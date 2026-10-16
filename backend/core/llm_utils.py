"""Helpers for OpenAI-compatible chat completion APIs."""
import os
from typing import Any, Dict, Iterable, List, Optional


def chat_request_options() -> Dict[str, Any]:
    """Only send the provider-specific thinking toggle when explicitly configured."""
    value = os.getenv("COURSEPILOT_ENABLE_THINKING", "").strip().lower()
    if value in ("true", "false"):
        return {"extra_body": {"enable_thinking": value == "true"}}
    return {}


def extract_text_content(content: Iterable[Any]) -> str:
    """Return text from either a plain string or structured content blocks."""
    if isinstance(content, str):
        return content

    texts: List[str] = []
    for block in content or []:
        if isinstance(block, str):
            texts.append(block)
            continue

        block_type = getattr(block, "type", None)
        text = getattr(block, "text", None)
        if isinstance(block, dict):
            block_type = block.get("type", block_type)
            text = block.get("text", text)

        if isinstance(text, str) and (block_type in (None, "text")):
            texts.append(text)

    return "\n".join(text for text in texts if text)


async def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: Optional[float] = None,
    system: Optional[str] = None,
) -> str:
    """Call an OpenAI-compatible chat-completions endpoint and return text."""
    request_messages: List[Dict[str, Any]] = list(messages)
    if system:
        request_messages.insert(0, {"role": "system", "content": system})

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": request_messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    kwargs.update(chat_request_options())
    response = await client.chat.completions.create(**kwargs)
    if not response.choices:
        return ""
    return extract_text_content(response.choices[0].message.content or "")
