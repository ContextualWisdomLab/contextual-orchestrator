"""Container probes: minimal public liveness and authenticated readiness."""
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


def test_healthz_is_unauthenticated_liveness() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("probe_agent", "mock-agent", tags=("reasoning",)),
        ModelAgent("disabled_probe_agent", "disabled-mock-agent", disabled=True),
    ])
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert body == {"status": "ok", "service": "contextual-orchestrator"}


def test_provider_readiness_refresh_is_authenticated_and_explicit() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("probe_agent", "mock-agent", tags=("reasoning",)),
        ModelAgent("disabled_probe_agent", "disabled-mock-agent", disabled=True),
    ])
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/api/v1/provider_readiness/latest"

    def request(path: str, token: str | None = "admin_secret") -> tuple[int, dict]:
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        req = urllib.request.Request(path, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    try:
        status, unprobed = request(url)
        assert status == 200
        assert unprobed["status"] == "unprobed"

        status, refreshed = request(f"{url}?refresh=true")
        assert status == 200
        assert refreshed["status"] == "ready"
        assert refreshed["ready_agent_count"] == 1
        assert refreshed["items"][1]["status"] == "disabled"

        try:
            request(f"{url}?refresh=true", token=None)
        except HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            raise AssertionError("provider readiness must require admin authentication")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_inference_provider_readiness_refresh_uses_inference_scope_only() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("probe_agent", "mock-agent", tags=("reasoning",)),
        ModelAgent("disabled_probe_agent", "disabled-mock-agent", disabled=True),
    ])
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/provider_readiness"

    def request(path: str, token: str | None) -> tuple[int, dict]:
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        req = urllib.request.Request(path, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    try:
        status, unprobed = request(url, "inference_secret")
        assert status == 200
        assert unprobed["status"] == "unprobed"
        assert unprobed["probe"] == "none"

        status, refreshed = request(f"{url}?refresh=true", "inference_secret")
        assert status == 200
        assert refreshed["status"] == "ready"
        assert refreshed["probe"] == "refresh"
        assert refreshed["ready_agent_count"] == 1
        assert refreshed["items"][1]["status"] == "disabled"

        try:
            request(url, "admin_secret")
        except HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            raise AssertionError("split-mode admin bearer must not authorize inference readiness")

        try:
            request(url, None)
        except HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            raise AssertionError("inference readiness must require inference authentication")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_healthz_is_unauthenticated_liveness()
    test_provider_readiness_refresh_is_authenticated_and_explicit()
    test_inference_provider_readiness_refresh_uses_inference_scope_only()
    print("ok")
