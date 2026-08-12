"""Container liveness vs readiness probe contracts."""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_ADMIN = "admin_secret"  # noqa: S105
_TEST_INFERENCE = "inference_secret"  # noqa: S105


def _start():
    orchestrator = TaskOrchestrator([ModelAgent("probe_agent", "mock-agent", tags=("reasoning",))])
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token=_TEST_ADMIN, inference_token=_TEST_INFERENCE),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_healthz_is_unauthenticated_minimal_liveness() -> None:
    server, thread, port = _start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert body == {"status": "ok", "service": "contextual-orchestrator"}
    # Operational inventory must not leak on unauthenticated liveness.
    for forbidden in (
        "agent_count",
        "batch_backend",
        "embedding_batch_backend",
        "usage_record_count",
        "agents",
        "ready",
    ):
        assert forbidden not in body


def test_readyz_requires_admin_and_exposes_inventory() -> None:
    server, thread, port = _start()
    try:
        unauth = urllib.request.Request(f"http://127.0.0.1:{port}/readyz")
        try:
            urllib.request.urlopen(unauth, timeout=5)
            raise AssertionError("readyz must require auth")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        inference = urllib.request.Request(
            f"http://127.0.0.1:{port}/readyz",
            headers={"authorization": f"Bearer {_TEST_INFERENCE}"},
        )
        try:
            urllib.request.urlopen(inference, timeout=5)
            raise AssertionError("readyz must not accept inference token")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        admin = urllib.request.Request(
            f"http://127.0.0.1:{port}/readyz",
            headers={"authorization": f"Bearer {_TEST_ADMIN}"},
        )
        with urllib.request.urlopen(admin, timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert body["status"] == "ready"
    assert body["service"] == "contextual-orchestrator"
    assert body["agent_count"] == 1
    assert body["batch_backend"]
    assert body["embedding_batch_backend"]
    assert body["usage_record_count"] == 0


if __name__ == "__main__":
    test_healthz_is_unauthenticated_minimal_liveness()
    test_readyz_requires_admin_and_exposes_inventory()
    print("ok")
