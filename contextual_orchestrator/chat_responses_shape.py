"""Bidirectional translation between the OpenAI Chat Completions and Responses shapes.

``ModelClient._proxy_send`` (``orchestrator.py``) is the one place a request
actually leaves the gateway for a provider. It calls into this module
whenever the caller's chosen public endpoint (``chat/completions`` or
``responses``) does not match what the selected agent natively speaks, so
the provider always receives its own native wire shape and the caller
always gets back a response in the shape it originally asked for.

Four pure functions cover both directions for both request and response
bodies -- mirroring ``model_discovery.py``'s ``style``-keyed catalog parsers
(``_parse_openai_compatible``/``_parse_bytez``): small, stateless, directly
testable functions rather than branching dispatch code embedded in a route
handler. Two capability-tag helpers decide, from an agent's declared
``ModelAgent.tags``, which shape(s) it natively speaks.

Not every field round-trips. The Responses API's built-in tool-use
primitives (``web_search_call``, ``computer_call``, ``mcp_call``,
``image_generation_call``, ``local_shell_call``) and reasoning-summary items
have no Chat Completions equivalent at all; :func:`responses_request_to_chat_request`
raises ``ValueError`` for them exactly as it did before this module existed
(ADR 0002's own admission: "unsupported Codex namespaces ... are not
forwarded"). Multiple ``tool_calls`` on one chat assistant turn become that
many separate Responses ``function_call`` items, which loses the fact they
originally shared one turn. See ``docs/planning/adrs/0126-openai-chat-responses-shape-translation.md``
for the full inventory of what is and is not preserved.
"""

from __future__ import annotations

from collections.abc import Iterable
import time
import uuid
from typing import Any

# Tag namespace this module owns on ``ModelAgent.tags``. Deliberately
# distinct from the pre-existing ``capability:`` prefix, which already means
# "this model can serve general chat text at all" -- a *modality* question
# answered by ``chat_capability.is_general_chat_candidate``. This prefix
# answers an orthogonal question: which OpenAI wire *shape* an agent's HTTP
# endpoint natively accepts. A model can be chat-capable (modality) while
# its endpoint only accepts the Responses wire shape, or vice versa.
#
# Both tags are *exclusivity* declarations, not additive ones: today's
# passthrough default (forward whatever shape the caller sent, unmodified)
# already works for the overwhelming common case -- every configured
# provider in ``model_discovery.PROVIDER_MODEL_SOURCES`` is OpenAI-compatible
# chat, and OpenAI's own real endpoint natively accepts *both* shapes, so an
# untagged agent must keep getting plain passthrough for both, exactly as it
# does today. A tag only fires when an agent is *proven* restricted to one
# shape -- mirroring ADR 0035's "capability tags are positive declarations,
# never a hard gate on absence": the declaration only ever adds a
# translation step for a provably-incompatible request, it never removes
# working passthrough from a provider nothing is known about.
CHAT_COMPLETIONS_ONLY_TAG = "api:chat_completions_only"
RESPONSES_ONLY_TAG = "api:responses_only"


def agent_supports_responses(tags: Iterable[str]) -> bool:
    """Return whether an agent may receive a Responses-shaped request as-is.

    True unless the agent positively declares :data:`CHAT_COMPLETIONS_ONLY_TAG`
    (proven restricted to Chat Completions). Absence of any tag preserves
    today's passthrough default rather than assuming incompatibility --
    the same "unproven is not known false" posture the org already takes
    for ``ModelAgent.reasoning_effort_supported``/``stream_usage_supported``.
    The one other proven chat-only signal, a loopback ``mlx://`` worker, is
    not tag-based and stays checked separately by the caller
    (``ModelClient._proxy_send``'s own ``_is_local_provider_url`` check).
    """
    return CHAT_COMPLETIONS_ONLY_TAG not in set(tags)


def agent_supports_chat_completions(tags: Iterable[str]) -> bool:
    """Return whether an agent may receive a Chat-Completions-shaped request as-is.

    True unless the agent positively declares :data:`RESPONSES_ONLY_TAG`
    (proven restricted to the Responses API) -- the mirror of
    :func:`agent_supports_responses`.
    """
    return RESPONSES_ONLY_TAG not in set(tags)


def _responses_text(value: Any) -> str:
    """Flatten a Responses string-or-content-parts field to plain text."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def _responses_text_format_to_chat_response_format(text: Any) -> dict[str, Any] | None:
    """Translate a Responses ``text.format`` control to a chat ``response_format``."""
    if not isinstance(text, dict) or not isinstance(text.get("format"), dict):
        return None
    fmt = text["format"]
    if fmt.get("type") in {"text", "json_object"}:
        return {"type": fmt["type"]}
    if fmt.get("type") != "json_schema":
        return None
    return {
        "type": "json_schema",
        "json_schema": {
            key: fmt[key]
            for key in ("name", "schema", "description", "strict")
            if key in fmt
        },
    }


def responses_request_to_chat_request(request: dict[str, Any]) -> dict[str, Any]:
    """Translate a Responses-shaped request into a Chat-Completions-shaped one.

    ``instructions`` becomes a leading ``system`` message; each ``input``
    item becomes one chat message (``function_call``/``function_call_output``
    items become an assistant ``tool_calls`` entry / a ``tool`` message).
    ``input_file``, ``reasoning``, and ``item_reference`` items carry no
    Chat Completions equivalent and are silently dropped; any other item
    type raises ``ValueError`` rather than forwarding an unsupported shape.
    """
    messages: list[dict[str, Any]] = []
    instructions = _responses_text(request.get("instructions"))
    if instructions:
        messages.append({"role": "system", "content": instructions})

    raw_input = request.get("input", "")
    if isinstance(raw_input, list):
        items = raw_input
    elif isinstance(raw_input, str):
        items = [{"type": "message", "role": "user", "content": raw_input}]
    else:
        raise ValueError("Responses input must be a string or item list")
    for item in items:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            raise ValueError("Responses input items must be objects")
        item_type = item.get("type", "message")
        if item_type == "message":
            role = item.get("role", "user")
            if role == "developer":
                role = "system"
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"unsupported Responses message role: {role}")
            raw_content = item.get("content")
            content: str | list[dict[str, Any]] = _responses_text(raw_content)
            if isinstance(raw_content, list):
                parts: list[dict[str, Any]] = []
                for part in raw_content:
                    if not isinstance(part, dict):
                        continue
                    part_type = part.get("type")
                    if part_type in {"input_text", "output_text", "text"} and isinstance(
                        part.get("text"), str
                    ):
                        parts.append({"type": "text", "text": part["text"]})
                    elif part_type in {"input_image", "image_url"}:
                        image_url = part.get("image_url")
                        if isinstance(image_url, str):
                            image_url = {
                                "url": image_url,
                                **(
                                    {"detail": part["detail"]}
                                    if isinstance(part.get("detail"), str)
                                    else {}
                                ),
                            }
                        if isinstance(image_url, dict):
                            parts.append({"type": "image_url", "image_url": image_url})
                if any(part.get("type") == "image_url" for part in parts):
                    content = parts
            if content:
                messages.append({"role": role, "content": content})
        elif item_type == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": str(item.get("call_id", "")),
                "content": _responses_text(item.get("output", item.get("content", ""))),
            })
        elif item_type == "function_call":
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": str(item.get("call_id", "")),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name", "")),
                        "arguments": str(item.get("arguments", "{}")),
                    },
                }],
            })
        elif item_type in {"input_file", "reasoning", "item_reference"}:
            continue
        else:
            raise ValueError(f"unsupported Responses input item: {item_type}")

    payload: dict[str, Any] = {
        "model": request.get("model", "local-model"),
        "messages": messages,
        "stream": False,
    }
    for key in (
        "temperature", "top_p", "max_tokens", "stop", "seed", "presence_penalty",
        "frequency_penalty", "logit_bias", "logprobs", "top_logprobs", "user",
        "parallel_tool_calls", "tool_choice",
    ):
        if key in request:
            payload[key] = request[key]
    if "max_output_tokens" in request and "max_tokens" not in payload:
        payload["max_tokens"] = request["max_output_tokens"]

    response_format = _responses_text_format_to_chat_response_format(request.get("text"))
    if response_format is None and isinstance(request.get("response_format"), dict):
        response_format = request["response_format"]
    if response_format is not None:
        payload["response_format"] = response_format

    tools: list[dict[str, Any]] = []
    for tool in request.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = {
            key: tool[key]
            for key in ("name", "description", "parameters", "strict")
            if key in tool
        }
        tools.append({"type": "function", "function": function})
    if tools:
        payload["tools"] = tools

    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_choice.get("name", "")},
        }
    return payload


def chat_response_to_responses_response(
    data: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Translate a Chat-Completions-shaped response into a Responses-shaped one."""
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") if isinstance(choice, dict) else {}
    message = message if isinstance(message, dict) else {}
    content = message.get("content")
    if not isinstance(content, str):
        content = message.get("reasoning") if isinstance(message.get("reasoning"), str) else ""

    output: list[dict[str, Any]] = []
    if content or not message.get("tool_calls"):
        output.append({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": content, "annotations": []}],
        })
    for tool_call in message.get("tool_calls", []):
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function") or {}
        output.append({
            "id": f"fc_{tool_call.get('id', uuid.uuid4().hex)}",
            "type": "function_call",
            "status": "completed",
            "call_id": str(tool_call.get("id", uuid.uuid4().hex)),
            "name": str(function.get("name", "")),
            "arguments": str(function.get("arguments", "{}")),
        })

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    input_tokens = int(usage.get("prompt_tokens", 0) or 0)
    output_tokens = int(usage.get("completion_tokens", 0) or 0)
    response: dict[str, Any] = {
        "id": f"resp_{data.get('id', uuid.uuid4().hex)}",
        "object": "response",
        "created_at": int(data.get("created", time.time())),
        "model": data.get("model", request.get("model", "local-model")),
        "output": output,
        "output_text": content,
        "status": "completed" if choice.get("finish_reason") != "length" else "incomplete",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        },
    }
    if isinstance(request.get("metadata"), dict):
        response["metadata"] = request["metadata"]
    return response


def chat_request_to_responses_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate a Chat-Completions-shaped request into a Responses-shaped one.

    The mirror of :func:`responses_request_to_chat_request`, needed when a
    caller's request arrives in Chat Completions shape but the selected
    agent only natively speaks the Responses API (declared via
    :data:`RESPONSES_SHAPE_TAG` with no :data:`CHAT_COMPLETIONS_SHAPE_TAG`).

    Every chat message with content becomes one Responses ``input`` item
    carrying the same role; text becomes ``output_text`` parts for the
    assistant role and ``input_text`` parts otherwise (OpenAI's own
    Responses convention), and ``image_url`` parts become ``input_image``
    parts. A tool-result message (``role: "tool"``) becomes a
    ``function_call_output`` item; an assistant message's ``tool_calls``
    become one ``function_call`` item per call -- which loses the fact
    several calls originally shared one assistant turn if there was more
    than one (see this module's docstring and the accompanying ADR).
    """
    input_items: list[dict[str, Any]] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": str(message.get("tool_call_id", "")),
                "output": _responses_text(message.get("content")),
            })
            continue
        tool_calls = message.get("tool_calls")
        if role == "assistant" and isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") or {}
                input_items.append({
                    "type": "function_call",
                    "call_id": str(tool_call.get("id", "")),
                    "name": str(function.get("name", "")),
                    "arguments": str(function.get("arguments", "{}")),
                })
        content = message.get("content")
        text_type = "output_text" if role == "assistant" else "input_text"
        if isinstance(content, str):
            if content:
                input_items.append({
                    "type": "message",
                    "role": role,
                    "content": [{"type": text_type, "text": content}],
                })
        elif isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "text" and isinstance(part.get("text"), str):
                    parts.append({"type": text_type, "text": part["text"]})
                elif part_type == "image_url" and part.get("image_url") is not None:
                    parts.append({"type": "input_image", "image_url": part["image_url"]})
            if parts:
                input_items.append({"type": "message", "role": role, "content": parts})

    payload_out: dict[str, Any] = {
        "model": payload.get("model", "local-model"),
        "input": input_items,
        "stream": False,
    }
    for key in (
        "temperature", "top_p", "stop", "seed", "presence_penalty",
        "frequency_penalty", "logit_bias", "logprobs", "top_logprobs", "user",
        "parallel_tool_calls", "tool_choice", "metadata",
    ):
        if key in payload:
            payload_out[key] = payload[key]
    if "max_tokens" in payload:
        payload_out["max_output_tokens"] = payload["max_tokens"]

    response_format = payload.get("response_format")
    if isinstance(response_format, dict):
        fmt_type = response_format.get("type")
        if fmt_type in {"text", "json_object"}:
            payload_out["text"] = {"format": {"type": fmt_type}}
        elif fmt_type == "json_schema" and isinstance(response_format.get("json_schema"), dict):
            schema = response_format["json_schema"]
            payload_out["text"] = {
                "format": {
                    "type": "json_schema",
                    **{
                        key: schema[key]
                        for key in ("name", "schema", "description", "strict")
                        if key in schema
                    },
                }
            }

    tools: list[dict[str, Any]] = []
    for tool in payload.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        tools.append({
            "type": "function",
            **{
                key: function[key]
                for key in ("name", "description", "parameters", "strict")
                if key in function
            },
        })
    if tools:
        payload_out["tools"] = tools

    tool_choice = payload_out.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        function = tool_choice.get("function")
        if isinstance(function, dict):
            payload_out["tool_choice"] = {"type": "function", "name": function.get("name", "")}

    return payload_out


def responses_response_to_chat_response(
    data: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Translate a Responses-shaped response into a Chat-Completions-shaped one.

    The mirror of :func:`chat_response_to_responses_response`, used to
    translate a Responses-only agent's real reply back into the shape a
    Chat Completions caller asked for. Reasoning-summary and built-in
    tool-use output items (``response.reasoning``, ``web_search_call``, and
    similar) have no chat equivalent and are dropped from the concatenated
    ``message.content`` rather than raising -- unlike the request-side
    translators, a caller-facing response must always return 200 with
    whatever chat-expressible content the provider produced.
    """
    content = ""
    tool_calls: list[dict[str, Any]] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "message":
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        content += text
        elif item_type == "function_call":
            tool_calls.append({
                "id": str(item.get("call_id", item.get("id", ""))),
                "type": "function",
                "function": {
                    "name": str(item.get("name", "")),
                    "arguments": str(item.get("arguments", "{}")),
                },
            })

    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls

    if tool_calls:
        finish_reason = "tool_calls"
    elif data.get("status") == "incomplete":
        finish_reason = "length"
    else:
        finish_reason = "stop"

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)

    raw_id = data.get("id")
    completion_id = (
        "chatcmpl_" + raw_id[len("resp_"):]
        if isinstance(raw_id, str) and raw_id.startswith("resp_")
        else f"chatcmpl_{uuid.uuid4().hex}"
    )
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(data.get("created_at", time.time())),
        "model": data.get("model", request.get("model", "local-model")),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        },
    }
