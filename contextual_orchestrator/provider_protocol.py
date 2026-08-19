"""Provider protocol translation for Chat Completions and Responses workers."""

from __future__ import annotations

from typing import Any


PROVIDER_PROTOCOLS = frozenset({"auto", "chat_completions", "responses"})
UNSUPPORTED_ENDPOINT_STATUSES = frozenset({404, 405, 415})


def validate_provider_protocol(value: str) -> str:
    """Validate the provider API protocol selector."""
    if value not in PROVIDER_PROTOCOLS:
        raise ValueError(
            "provider_protocol must be one of auto, chat_completions, or responses"
        )
    return value


def omit_empty_model(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove the blank model marker so the provider/orchestrator can select it."""
    normalized = dict(payload)
    if not normalized.get("model"):
        normalized.pop("model", None)
    return normalized


def _responses_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError("chat message content must be text or content blocks")
    result: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("chat content blocks must be objects")
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            result.append({"type": "input_text", "text": block["text"]})
            continue
        if block_type == "image_url":
            image = block.get("image_url")
            url = image.get("url") if isinstance(image, dict) else None
            if not isinstance(url, str):
                raise ValueError("image_url content block requires a URL")
            converted: dict[str, Any] = {"type": "input_image", "image_url": url}
            if isinstance(image, dict) and isinstance(image.get("detail"), str):
                converted["detail"] = image["detail"]
            result.append(converted)
            continue
        raise ValueError(f"unsupported Chat Completions content block: {block_type}")
    return result


def chat_to_responses_payload(payload: dict[str, Any], max_output_tokens: int) -> dict[str, Any]:
    """Translate a validated Chat Completions request to Responses input."""
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Chat Completions payload requires messages")
    inputs: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Chat Completions messages must be objects")
        role = message.get("role")
        if role == "system":
            role = "developer"
        if role not in {"developer", "user", "assistant"}:
            raise ValueError(f"unsupported Chat Completions role for Responses: {role}")
        inputs.append({"role": role, "content": _responses_content(message.get("content"))})

    result = omit_empty_model({
        "model": payload.get("model"),
        "input": inputs,
        "stream": bool(payload.get("stream", False)),
        "max_output_tokens": payload.get("max_output_tokens", payload.get("max_tokens", max_output_tokens)),
    })
    for key in ("temperature", "top_p", "stop", "seed", "user", "metadata"):
        if key in payload:
            result[key] = payload[key]
    response_format = payload.get("response_format")
    if isinstance(response_format, dict):
        format_type = response_format.get("type")
        if format_type == "json_schema" and isinstance(response_format.get("json_schema"), dict):
            schema = response_format["json_schema"]
            result["text"] = {"format": {"type": "json_schema", **schema}}
        elif format_type == "json_object":
            result["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "response",
                    "schema": {"type": "object"},
                    "strict": False,
                }
            }
    tools = payload.get("tools")
    if isinstance(tools, list):
        result["tools"] = [
            {"type": "function", **tool["function"]}
            for tool in tools
            if isinstance(tool, dict)
            and tool.get("type") == "function"
            and isinstance(tool.get("function"), dict)
        ]
    return result


def responses_text(response: dict[str, Any]) -> str:
    """Extract assistant text from a Responses API result."""
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text
    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                if isinstance(content.get("text"), str):
                    parts.append(content["text"])
    return "".join(parts)


def responses_to_chat_response(response: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Adapt a provider Responses result for a Chat Completions caller."""
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    return {
        "id": response.get("id", "response-adapted"),
        "object": "chat.completion",
        "model": response.get("model", request.get("model", "")),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": responses_text(response)},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        },
    }
