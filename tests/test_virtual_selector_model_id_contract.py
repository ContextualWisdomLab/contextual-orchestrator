"""The virtual-selector gate matches exact model ids and fails closed otherwise.

``server`` routes tools-bearing requests onto the Fugu control plane only when
the model id matches one of the virtual selectors exactly. ``_validate_chat_model``
applies ``.strip()`` and a length check and nothing else -- no provider-prefix
stripping and no case folding -- so a provider-qualified or differently-cased
alias is rejected before it can reach the ``named_tool_passthrough`` branch.

That rejection is the contract, not an accident. Normalizing these aliases
"helpfully" would widen the exact-match gate silently and send requests that
callers never routed into single-agent passthrough, losing worker re-selection.
These cases exist so that change cannot land unnoticed.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server

_TEST_AUTH_TOKEN = "virtual_selector_contract_token"  # noqa: S105
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inspect_repository",
            "description": "Inspect the trusted workspace",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _free_agents() -> list[ModelAgent]:
    return [
        ModelAgent(
            "primary_free_agent",
            "primary-free-model",
            priority=10,
            provider_name="primary",
            tags=("cost:free", "reasoning", "coding"),
        ),
        ModelAgent(
            "fallback_free_agent",
            "fallback-free-model",
            priority=1,
            provider_name="fallback",
            tags=("cost:free", "reasoning", "coding"),
        ),
    ]


def _post(port: int, model: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "scan the trusted workspace"}],
                "tools": _TOOLS,
            }
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_virtual_selector_accepts_exact_ids_and_rejects_aliases() -> None:
    """Exact virtual ids route; provider-qualified and re-cased aliases are refused."""
    orchestrator = TaskOrchestrator(_free_agents())
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    observed: dict[str, tuple[int, str | None]] = {}
    try:
        port = server.server_address[1]
        for model in (
            TaskOrchestrator.FREE_MODEL,
            f"  {TaskOrchestrator.FREE_MODEL}  ",
            f"openai/{TaskOrchestrator.FREE_MODEL}",
            f"openai/{TaskOrchestrator.GATEWAY_DEFAULT_MODEL}",
            TaskOrchestrator.FREE_MODEL.upper(),
        ):
            status, body = _post(port, model)
            mode = (body.get("orchestration") or {}).get("mode")
            code = (body.get("error") or {}).get("code")
            observed[model] = (status, mode or code)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    # Exact id, and the same id with surrounding whitespace, stay on the route path.
    assert observed[TaskOrchestrator.FREE_MODEL] == (200, "route"), observed
    assert observed[f"  {TaskOrchestrator.FREE_MODEL}  "] == (200, "route"), observed

    # A provider-qualified alias is refused outright rather than falling through
    # to single-agent passthrough, where worker re-selection would be lost.
    assert observed[f"openai/{TaskOrchestrator.FREE_MODEL}"] == (400, "invalid_model"), observed
    assert observed[f"openai/{TaskOrchestrator.GATEWAY_DEFAULT_MODEL}"] == (
        400,
        "invalid_model",
    ), observed

    # No case folding either.
    assert observed[TaskOrchestrator.FREE_MODEL.upper()] == (400, "invalid_model"), observed
