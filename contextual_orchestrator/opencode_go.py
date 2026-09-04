"""Protocol evidence and adapters for the OpenCode Go model catalog."""

from __future__ import annotations

import json
from typing import Any


NATIVE_ENDPOINTS = {
    **dict.fromkeys(
        (
            "grok-4.6",
            "gpt-5.6-luna",
            "muse-spark-1.3-contributor",
            "muse-spark-1.2-contributor",
        ),
        "responses",
    ),
    **dict.fromkeys(
        (
            "glm-5.3-flash",
            "glm-5.3",
            "glm-5.2",
            "glm-5.1",
            "kimi-k3",
            "kimi-k2.7-code",
            "kimi-k2.6",
            "longcat-2.0",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
            "mimo-v2.5",
            "mimo-v2.5-pro",
            "hy4-preview",
            "hy3",
        ),
        "chat/completions",
    ),
    **dict.fromkeys(
        (
            "minimax-m3",
            "minimax-m2.7",
            "minimax-m2.5",
            "qwen3.8-max",
            "qwen3.8-flash",
            "qwen3.7-max",
            "qwen3.7-plus",
            "qwen3.6-plus",
        ),
        "messages",
    ),
}


def chat_to_responses(request: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": request.get("model"),
        "input": request.get("messages", []),
        "max_output_tokens": request.get("max_tokens"),
    }
    for key in ("temperature", "top_p"):
        if key in request:
            payload[key] = request[key]
    if "tools" in request:
        payload["tools"] = []
        for tool in request["tools"]:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                raise ValueError("Responses conversion supports function tools only")
            payload["tools"].append({"type": "function", **function})
    choice = request.get("tool_choice")
    if isinstance(choice, dict) and isinstance(choice.get("function"), dict):
        payload["tool_choice"] = {
            "type": "function",
            "name": choice["function"].get("name"),
        }
    elif choice is not None:
        payload["tool_choice"] = choice
    return payload


def chat_to_messages(request: dict[str, Any]) -> dict[str, Any]:
    unsupported = set(request) - {
        "model",
        "messages",
        "max_tokens",
        "stream",
        "temperature",
        "top_p",
        "stop",
        "tools",
        "tool_choice",
    }
    if unsupported:
        raise ValueError("Messages conversion does not support all requested controls")
    messages: list[dict[str, Any]] = []
    system: list[str] = []
    for message in request.get("messages", []):
        if not isinstance(message, dict):
            raise ValueError("chat messages must be objects")
        role, content = message.get("role"), message.get("content", "")
        if role in {"system", "developer"}:
            if not isinstance(content, str):
                raise ValueError("Messages system content must be text")
            system.append(content)
            continue
        if role == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(message.get("tool_call_id", "")),
                            "content": str(content),
                        }
                    ],
                }
            )
            continue
        if role not in {"user", "assistant"}:
            raise ValueError(f"unsupported Messages role: {role}")
        blocks: list[dict[str, Any]] = []
        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if (
                    not isinstance(part, dict)
                    or part.get("type") != "text"
                    or not isinstance(part.get("text"), str)
                ):
                    raise ValueError("Messages conversion supports text content only")
                blocks.append({"type": "text", "text": part["text"]})
        elif content != "" and content is not None:
            raise ValueError("Messages content must be text")
        for tool_call in message.get("tool_calls", []):
            function = (
                tool_call.get("function") if isinstance(tool_call, dict) else None
            )
            if not isinstance(function, dict):
                raise ValueError("Messages tool calls must contain a function")
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Messages tool arguments must be valid JSON") from exc
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(tool_call.get("id", "")),
                    "name": str(function.get("name", "")),
                    "input": arguments,
                }
            )
        messages.append({"role": role, "content": blocks})
    payload: dict[str, Any] = {
        "model": request.get("model"),
        "messages": messages,
        "max_tokens": request.get("max_tokens", 1024),
    }
    if system:
        payload["system"] = "\n\n".join(system)
    for key in ("temperature", "top_p"):
        if key in request:
            payload[key] = request[key]
    if "stop" in request:
        payload["stop_sequences"] = request["stop"]
    tools = []
    for tool in request.get("tools", []):
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            raise ValueError("Messages conversion supports function tools only")
        tools.append(
            {
                "name": function.get("name"),
                "description": function.get("description", ""),
                "input_schema": function.get("parameters", {"type": "object"}),
            }
        )
    if tools:
        payload["tools"] = tools
    choice = request.get("tool_choice")
    if choice in {"auto", "required"}:
        payload["tool_choice"] = {"type": "auto" if choice == "auto" else "any"}
    elif isinstance(choice, dict) and isinstance(choice.get("function"), dict):
        payload["tool_choice"] = {
            "type": "tool",
            "name": choice["function"].get("name"),
        }
    elif choice not in {None, "none"}:
        raise ValueError("unsupported Messages tool choice")
    return payload


def messages_to_chat(data: dict[str, Any]) -> dict[str, Any]:
    text: list[str] = []
    calls: list[dict[str, Any]] = []
    for block in data.get("content", []):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text.append(block["text"])
        elif block.get("type") == "tool_use":
            calls.append(
                {
                    "id": str(block.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name", "")),
                        "arguments": json.dumps(
                            block.get("input", {}), separators=(",", ":")
                        ),
                    },
                }
            )
        else:
            raise ValueError("Messages response contained an unsupported content block")
    reason = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }.get(data.get("stop_reason"))
    if reason is None:
        raise ValueError("Messages response contained an unsupported stop reason")
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text)}
    if calls:
        message["tool_calls"] = calls
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt, completion = (
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
    )
    return {
        "id": data.get("id"),
        "object": "chat.completion",
        "model": data.get("model"),
        "choices": [{"index": 0, "message": message, "finish_reason": reason}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def responses_to_chat(data: dict[str, Any]) -> dict[str, Any]:
    text: list[str] = []
    calls: list[dict[str, Any]] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content", []):
                if (
                    isinstance(part, dict)
                    and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ):
                    text.append(part["text"])
        elif item.get("type") == "function_call":
            calls.append(
                {
                    "id": str(item.get("call_id", "")),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name", "")),
                        "arguments": str(item.get("arguments", "{}")),
                    },
                }
            )
        else:
            raise ValueError("Responses result contained an unsupported output item")
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text)}
    if calls:
        message["tool_calls"] = calls
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt, completion = (
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
    )
    return {
        "id": data.get("id"),
        "object": "chat.completion",
        "model": data.get("model"),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": int(usage.get("total_tokens", prompt + completion) or 0),
        },
    }
