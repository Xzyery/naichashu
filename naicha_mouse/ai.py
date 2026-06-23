"""AI chat logic — request building, response parsing, URL normalisation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from naicha_mouse.constants import AI_SYSTEM_PROMPT


def normalize_ai_url(base_url: str, provider: str = "openai", model: str = "") -> str:
    url = base_url.strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    url = url.rstrip("/")
    if provider == "anthropic":
        if url.endswith("/messages"):
            return url
        return url + "/v1/messages" if not url.endswith("/v1") else url + "/messages"
    if provider == "gemini":
        if ":generateContent" in url:
            return url
        base = url if url.endswith("/v1") or url.endswith("/v1beta") else url + "/v1beta"
        return f"{base}/models/{model}:generateContent"
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def ai_messages_for_request(chat_history: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": AI_SYSTEM_PROMPT},
        *chat_history[-8:],
    ]


def build_ai_request(
    ai_config: dict[str, str],
    chat_history: list[dict[str, str]],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    provider = ai_config.get("provider", "openai")
    model = ai_config.get("model", "").strip()
    api_key = ai_config.get("api_key", "").strip()
    url = normalize_ai_url(ai_config.get("base_url", ""), provider, model)
    messages = ai_messages_for_request(chat_history)

    if provider == "anthropic":
        user_messages = [message for message in messages if message["role"] != "system"]
        payload = {
            "model": model,
            "system": AI_SYSTEM_PROMPT,
            "messages": user_messages,
            "max_tokens": 260,
            "temperature": 0.8,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        return url, headers, payload

    if provider == "gemini":
        contents = []
        for message in messages:
            if message["role"] == "system":
                continue
            role = "model" if message["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        payload = {
            "systemInstruction": {"parts": [{"text": AI_SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.8,
                "maxOutputTokens": 260,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        return url, headers, payload

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 260,
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return url, headers, payload


def parse_ai_reply(result: dict[str, Any], provider: str = "openai") -> str:
    if provider == "anthropic":
        parts = result.get("content", [])
        text = "".join(str(part.get("text", "")) for part in parts if part.get("type") == "text")
        return text.strip()
    if provider == "gemini":
        candidates = result.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(str(part.get("text", "")) for part in parts)
        return text.strip()
    return (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )


def request_ai_reply(
    ai_config: dict[str, str],
    chat_history: list[dict[str, str]],
    on_success: Any,
    on_error: Any,
) -> None:
    """Blocking — call from a background thread. Emits result via pyqtSignal callbacks."""
    try:
        url, headers, payload = build_ai_request(ai_config, chat_history)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
        result = json.loads(raw)
        reply = parse_ai_reply(result, ai_config.get("provider", "openai"))
        if not reply:
            raise RuntimeError("模型没有返回可显示的内容")
        on_success.emit(reply)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:220]
        on_error.emit(f"AI 请求失败：HTTP {error.code} {detail}")
    except Exception as error:
        on_error.emit(f"AI 请求失败：{error}")


def trim_chat_history(chat_history: list[dict[str, str]], max_len: int = 12) -> list[dict[str, str]]:
    if len(chat_history) > max_len:
        return chat_history[-max_len:]
    return chat_history
