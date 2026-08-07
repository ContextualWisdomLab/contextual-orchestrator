"""Deployment readiness probe contracts for the standalone HTTP server."""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _request_json(url: str) -> tuple[int, dict[str, Any]]:
    """Fetch one JSON probe response, including deliberate HTTP error bodies."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


def _run_probe(security: SecurityConfig, agent: ModelAgent, path: str) -> tuple[int, dict[str, Any]]:
    """Serve one isolated probe request and return its status plus JSON body."""
    orchestrator = TaskOrchestrator([agent])
    server = build_server(orchestrator, port=0, security=security)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        return _request_json(f"http://127.0.0.1:{port}{path}")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_readyz_is_unauthenticated_and_ready_for_a_configured_runtime() -> None:
    status, body = _run_probe(
        SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
        ModelAgent("probe_agent", "mock-agent", tags=("reasoning",)),
        "/readyz",
    )

    assert status == 200
    assert body == {
        "status": "ready",
        "service": "contextual-orchestrator",
        "checks": {
            "auth_configured": True,
            "enabled_agent_count": 1,
            "batch_backend_configured": True,
            "embedding_batch_backend_configured": True,
        },
        "blocking_checks": [],
    }


def test_readyz_fails_closed_when_authentication_is_not_configured() -> None:
    status, body = _run_probe(
        SecurityConfig(),
        ModelAgent("probe_agent", "mock-agent", tags=("reasoning",)),
        "/readyz",
    )

    assert status == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["auth_configured"] is False
    assert body["blocking_checks"] == ["auth_configured"]


def test_readyz_fails_closed_when_no_agent_is_enabled() -> None:
    status, body = _run_probe(
        SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
        ModelAgent("probe_agent", "mock-agent", tags=("reasoning",), disabled=True),
        "/readyz",
    )

    assert status == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["enabled_agent_count"] == 0
    assert body["blocking_checks"] == ["enabled_agents"]


def test_liveness_stays_up_when_readiness_is_blocked() -> None:
    security = SecurityConfig()
    agent = ModelAgent("probe_agent", "mock-agent", tags=("reasoning",), disabled=True)

    ready_status, _ = _run_probe(security, agent, "/readyz")
    live_status, live_body = _run_probe(security, agent, "/healthz")

    assert ready_status == 503
    assert live_status == 200
    assert live_body["status"] == "ok"


def test_readyz_exposes_no_secret_or_provider_configuration() -> None:
    status, body = _run_probe(
        SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
        ModelAgent(
            "probe_agent",
            "mock-agent",
            base_url="mock://private-provider-name",
            credential_key="PRIVATE_PROVIDER_TOKEN",
            tags=("reasoning",),
        ),
        "/readyz",
    )

    rendered = json.dumps(body, sort_keys=True)
    assert status == 200
    assert "admin_secret" not in rendered
    assert "inference_secret" not in rendered
    assert "PRIVATE_PROVIDER_TOKEN" not in rendered
    assert "private-provider-name" not in rendered


if __name__ == "__main__":
    test_readyz_is_unauthenticated_and_ready_for_a_configured_runtime()
    test_readyz_fails_closed_when_authentication_is_not_configured()
    test_readyz_fails_closed_when_no_agent_is_enabled()
    test_liveness_stays_up_when_readiness_is_blocked()
    test_readyz_exposes_no_secret_or_provider_configuration()
    print("ok")
