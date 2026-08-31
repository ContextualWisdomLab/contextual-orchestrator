"""End-to-end coverage for the PR #958 round-3 Devin finding.

``TaskOrchestrator.proxy_completion`` is the single-agent passthrough the
server's tool-loop path (``tool_loop=True`` on ``/v1/chat/completions``)
calls with ``effort_profile=None`` -- it never resolved the opted-in
``role_effort_catalog`` on its own, so a tool request silently omitted the
catalog's sampling, token, seed, and reasoning_effort settings even while
every other request path (route/conduct/stream/batch, and
``_orchestrated_provider_completion``'s own ``"synthesizer"`` fallback)
honored it. ``proxy_completion`` now defaults an unset ``effort_profile`` to
the catalog's ``"worker"`` entry (the role every selection/failover call in
that method already uses), mirroring the pre-existing
``effort_profile or self._role_effort_profile("synthesizer")`` pattern in
``_orchestrated_provider_completion``. This drives a real HTTP tool-loop
request through the running server and inspects what actually reached
``ModelClient.apply_effort_profile``.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.reasoning_effort_profile import (  # noqa: E402
    default_role_effort_catalog,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "tool_loop_role_effort_catalog_http_token"  # noqa: S105


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_tool_loop_request_inherits_the_worker_role_effort_profile() -> None:
    """A tool request with no explicit profile still gets the catalog's worker settings."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))],
        role_effort_catalog=default_role_effort_catalog(),
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    captured: dict[str, object] = {}
    original_apply_effort_profile = orchestrator.client.apply_effort_profile

    def _capture_apply_effort_profile(agent, payload, profile, *, api_surface="chat.completions"):
        result = original_apply_effort_profile(
            agent, payload, profile, api_surface=api_surface
        )
        captured.update(result)
        return result

    try:
        with patch.object(
            orchestrator.client,
            "apply_effort_profile",
            side_effect=_capture_apply_effort_profile,
        ):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "use a tool"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup_balance",
                                "description": "Fetch account balance",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"account_id": {"type": "string"}},
                                },
                            },
                        }
                    ],
                },
            )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert captured, "apply_effort_profile was never invoked for the tool-loop request"
    worker_profile = default_role_effort_catalog()["worker"]
    assert captured["temperature"] == worker_profile.temperature
    assert captured["top_p"] == worker_profile.top_p
    assert captured["seed"] == worker_profile.seed
    assert captured["max_tokens"] == worker_profile.max_output_tokens
    assert captured["reasoning_effort"] == worker_profile.reasoning_effort


def test_http_tool_loop_request_without_catalog_is_unchanged() -> None:
    """No opted-in role_effort_catalog: the tool-loop request carries no profile fields."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    captured: dict[str, object] = {}
    original_apply_effort_profile = orchestrator.client.apply_effort_profile

    def _capture_apply_effort_profile(agent, payload, profile, *, api_surface="chat.completions"):
        result = original_apply_effort_profile(
            agent, payload, profile, api_surface=api_surface
        )
        captured.update(result)
        return result

    try:
        with patch.object(
            orchestrator.client,
            "apply_effort_profile",
            side_effect=_capture_apply_effort_profile,
        ):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "use a tool"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup_balance",
                                "parameters": {"type": "object", "properties": {}},
                            },
                        }
                    ],
                },
            )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    # apply_effort_profile may still run with profile=None (a no-op besides
    # the default max_tokens); it must never fabricate reasoning_effort/seed.
    assert "reasoning_effort" not in captured
    assert "seed" not in captured


if __name__ == "__main__":
    test_http_tool_loop_request_inherits_the_worker_role_effort_profile()
    test_http_tool_loop_request_without_catalog_is_unchanged()
    print("ok")
