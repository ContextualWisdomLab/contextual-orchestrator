"""Container liveness vs readiness probe contracts."""
from __future__ import annotations

import json
import sys
import threading
import time
from types import SimpleNamespace
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
    assert all(item["ready"] for item in body["dependencies"].values())


class _UnreadyDependency:
    """Dependency fixture that reports an operational failure."""

    name = "unready"

    def readiness_check(self):
        """Return a deterministic failed readiness result."""
        return {"ready": False, "reason": "fixture_failure"}


class _SlowDependency:
    """Dependency fixture that exceeds the configured readiness deadline."""

    name = "slow"

    def readiness_check(self):
        """Block long enough to prove the server returns a bounded response."""
        time.sleep(1)
        return {"ready": True}


class _ReadyLedger:
    """Minimal ledger fixture for readiness-only server tests."""

    name = "ready"

    def records(self):
        """Return an empty prompt-safe inventory."""
        return []

    def readiness_check(self):
        """Return a successful readiness result."""
        return {"ready": True}


def _readiness_server(batch_backend, embedding_backend, timeout=0.05):
    orch = TaskOrchestrator([ModelAgent("probe_agent", "mock-agent", tags=("reasoning",))])
    coordinator = SimpleNamespace(
        batch_backend=batch_backend,
        embedding_batch_backend=embedding_backend,
        ledger=_ReadyLedger(),
    )
    server = build_server(
        orch,
        port=0,
        security=SecurityConfig(
            admin_token=_TEST_ADMIN,
            inference_token=_TEST_INFERENCE,
            readiness_probe_timeout_seconds=timeout,
        ),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_readyz_reports_failed_dependency_as_degraded() -> None:
    server, thread, port = _readiness_server(_UnreadyDependency(), _ReadyLedger())
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/readyz",
        headers={"authorization": f"Bearer {_TEST_ADMIN}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raise AssertionError(f"expected 503, got {response.status}")
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        assert exc.code == 503
        assert body["status"] == "degraded"
        assert body["dependencies"]["batch_backend"]["reason"] == "fixture_failure"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_readyz_bounds_slow_dependency_probe() -> None:
    server, thread, port = _readiness_server(_SlowDependency(), _ReadyLedger(), timeout=0.02)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/readyz",
        headers={"authorization": f"Bearer {_TEST_ADMIN}"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raise AssertionError(f"expected 503, got {response.status}")
    except urllib.error.HTTPError as exc:
        assert exc.code == 503
        assert time.monotonic() - started < 0.5
        body = json.loads(exc.read().decode("utf-8"))
        assert body["dependencies"]["batch_backend"]["reason"] == "readiness_probe_timeout"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_healthz_is_unauthenticated_minimal_liveness()
    test_readyz_requires_admin_and_exposes_inventory()
    test_readyz_reports_failed_dependency_as_degraded()
    test_readyz_bounds_slow_dependency_probe()
    print("ok")
