"""Buyer ops/SDK compatibility: /health alias and system_fingerprint on chat completions."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import chat_completion_chunks, chat_completion_response  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "health_fp_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_chat_completion_response_includes_system_fingerprint() -> None:
    body = chat_completion_response(
        {"answer": "ok", "mode": "route", "workflow_run_id": "run_1"},
        model="mock-generalist",
    )
    assert body["system_fingerprint"] == "fp_contextual_orchestrator"
    chunks = chat_completion_chunks({"answer": "ok", "mode": "route"})
    assert all(c.get("system_fingerprint") == "fp_contextual_orchestrator" for c in chunks)


def test_health_alias_matches_healthz_without_auth() -> None:
    """Cloud/LB defaults often probe /health, not /healthz."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            healthz = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert healthz["status"] == "ok"
    assert health["status"] == "ok"
    assert health["service"] == healthz["service"] == "contextual-orchestrator"
    assert health["agent_count"] == healthz["agent_count"]


def test_http_chat_completion_exposes_system_fingerprint() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "orchestration": "route",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert body["system_fingerprint"] == "fp_contextual_orchestrator"
    assert body["object"] == "chat.completion"


if __name__ == "__main__":
    test_chat_completion_response_includes_system_fingerprint()
    test_health_alias_matches_healthz_without_auth()
    test_http_chat_completion_exposes_system_fingerprint()
    print("ok")
