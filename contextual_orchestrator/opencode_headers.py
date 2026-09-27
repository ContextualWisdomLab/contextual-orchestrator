"""Client identification headers OpenCode Zen and Go ask integrators to send.

The OpenCode Go documentation (https://opencode.ai/docs/go/#where-can-i-use-it,
checked 2026-09-26) asks every client to identify itself with its own user
agent instead of a generic HTTP-library name, and to send a stable session ID
in ``x-opencode-session`` for each conversation so OpenCode can route and
prompt-cache it. Requests to any other provider get no extra headers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

OPENCODE_PROVIDER_NAMES = frozenset({"opencode_zen", "opencode_go"})
OPENCODE_HOST = "opencode.ai"
OPENCODE_SESSION_HEADER = "x-opencode-session"
OPENCODE_USER_AGENT = (
    "contextual-orchestrator/0.2.0 "
    "(+https://github.com/ContextualWisdomLab/contextual-orchestrator)"
)
_MAX_CALLER_SESSION_CHARS = 128


def _is_opencode_agent(agent: Any) -> bool:
    if getattr(agent, "provider_name", None) in OPENCODE_PROVIDER_NAMES:
        return True
    base_url = getattr(agent, "base_url", "")
    if not isinstance(base_url, str) or not base_url:
        return False
    host = (urlsplit(base_url).hostname or "").casefold()
    return host == OPENCODE_HOST or host.endswith("." + OPENCODE_HOST)


def _caller_session_id(payload: Mapping[str, Any]) -> str | None:
    """Return a caller-chosen conversation key when the request carries one."""
    for field in ("prompt_cache_key", "session_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_MAX_CALLER_SESSION_CHARS]
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("session_id")
        if isinstance(value, str) and value.strip():
            return value.strip()[:_MAX_CALLER_SESSION_CHARS]
    return None


def _conversation_prefix(payload: Mapping[str, Any]) -> Any:
    """Return the part of a request that stays fixed across one conversation.

    Every turn of a chat conversation resends the same opening system and
    first user message, so hashing that prefix yields the same ID on each
    turn without storing any state. Responses-style ``instructions`` and the
    first ``input`` item play the same role there.
    """
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        prefix: list[Any] = []
        for message in messages:
            prefix.append(message)
            if isinstance(message, Mapping) and message.get("role") == "user":
                break
        return {"messages": prefix}
    input_value = payload.get("input")
    if isinstance(input_value, list) and input_value:
        input_value = input_value[0]
    return {"instructions": payload.get("instructions"), "input": input_value}


def opencode_session_id(payload: Mapping[str, Any]) -> str:
    """Return a stable, non-reversible session ID for one conversation."""
    caller = _caller_session_id(payload)
    if caller is not None:
        return caller
    canonical = json.dumps(
        _conversation_prefix(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"co-{digest}"


def opencode_request_headers(agent: Any, payload: Mapping[str, Any]) -> dict[str, str]:
    """Return the OpenCode identification headers for one provider request."""
    if not _is_opencode_agent(agent):
        return {}
    return {
        "user-agent": OPENCODE_USER_AGENT,
        OPENCODE_SESSION_HEADER: opencode_session_id(payload),
    }
