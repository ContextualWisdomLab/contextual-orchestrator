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

        try:
            request(f"{url}?refresh=true")
        except HTTPError as exc:
            assert exc.code == 409
            body = json.loads(exc.read().decode("utf-8"))
            assert body["error"]["code"] == "async_readiness_refresh_required"
        else:  # pragma: no cover
            raise AssertionError("inline broad readiness refresh must not run")

        try:
            request(f"{url}?refresh=true", token=None)
        except HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            raise AssertionError("provider readiness must require admin authentication")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_healthz_is_unauthenticated_liveness()
    test_provider_readiness_refresh_is_authenticated_and_explicit()
    print("ok")
