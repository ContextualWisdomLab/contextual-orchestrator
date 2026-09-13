"""Issue #926: inference-scoped readiness probe, narrower than the admin report."""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from urllib.error import HTTPError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _build_orchestrator() -> TaskOrchestrator:
    return TaskOrchestrator([
        ModelAgent(
            "probe_agent",
            "mock-agent",
            tags=("reasoning",),
            provider_name="mock_provider",
            credential_key="MOCK_PROVIDER_API_KEY",
        ),
        ModelAgent("disabled_probe_agent", "disabled-mock-agent", disabled=True),
    ])


def _request(url: str, token: str | None) -> tuple[int, dict]:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_inference_readiness_returns_per_candidate_diagnostics_with_inference_token() -> None:
    server = build_server(
        _build_orchestrator(),
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/readiness"

    try:
        status, unprobed = _request(url, "inference_secret")
        assert status == 200
        assert unprobed["status"] == "unprobed"
        assert unprobed["probed_count"] == 1  # disabled agent excluded from the active count
        assert unprobed["items"][0] == {
            "agent_id": "probe_agent",
            "model": "mock-agent",
            "provider_name": "mock_provider",
            "status": "unprobed",
        }
        assert unprobed["items"][1]["status"] == "disabled"

        status, refreshed = _request(f"{url}?refresh=true", "inference_secret")
        assert status == 200
        assert refreshed["status"] == "ready"
        assert refreshed["ready_count"] == 1
        assert refreshed["probed_count"] == 1
        ready_item = refreshed["items"][0]
        assert ready_item["agent_id"] == "probe_agent"
        assert ready_item["status"] == "ready"
        assert "latency_ms" in ready_item
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_inference_readiness_rejects_missing_or_wrong_scope_token() -> None:
    server = build_server(
        _build_orchestrator(),
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/readiness"
    models_url = f"http://127.0.0.1:{port}/v1/models"

    try:
        no_token_status, _ = _request(url, None)
        wrong_scope_status, _ = _request(url, "admin_secret")

        # Same status /v1/models already uses for unauthorized access.
        no_token_models_status, _ = _request(models_url, None)
        wrong_scope_models_status, _ = _request(models_url, "admin_secret")

        assert no_token_status == no_token_models_status == 401
        assert wrong_scope_status == wrong_scope_models_status == 401
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_inference_readiness_never_leaks_admin_only_fields() -> None:
    orchestrator = _build_orchestrator()
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        admin_status, admin_report = _request(
            f"http://127.0.0.1:{port}/api/v1/provider_readiness/latest?refresh=true", "admin_secret"
        )
        assert admin_status == 200
        assert admin_report["status"] == "ready"
        # "usage" is present on the admin-scoped ready item -- confirm it is
        # actually admin-only data present in the full report, not a field
        # that never existed to begin with.
        assert "usage" in admin_report["items"][0]

        status, inference_report = _request(
            f"http://127.0.0.1:{port}/v1/readiness?refresh=true", "inference_secret"
        )
        assert status == 200
        serialized = json.dumps(inference_report)
        assert "usage" not in serialized
        assert "credential_key" not in serialized
        assert "base_url" not in serialized
        assert "MOCK_PROVIDER_API_KEY" not in serialized
        for item in inference_report["items"]:
            assert set(item) <= {
                "agent_id",
                "model",
                "provider_name",
                "status",
                "failure_code",
                "latency_ms",
                "rate_limited_until",
                "earliest_ready_seconds",
            }
            assert "usage" not in item
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_inference_readiness_returns_per_candidate_diagnostics_with_inference_token()
    test_inference_readiness_rejects_missing_or_wrong_scope_token()
    test_inference_readiness_never_leaks_admin_only_fields()
    print("ok")
