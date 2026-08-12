"""Trace disclosure requires authority beyond ordinary inference access."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_ADMIN = "admin_secret"  # noqa: S105
_INFERENCE = "inference_secret"  # noqa: S105
_SINGLE = "single_token"  # noqa: S105


def post(url: str, payload: dict, token: str, extra_headers: dict[str, str] | None = None) -> tuple[int, dict]:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "connection": "close",
    }
    headers.update(extra_headers or {})
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_inference_token_cannot_obtain_orchestration_trace() -> None:
    orch = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])
    server = build_server(
        orch,
        port=0,
        security=SecurityConfig(admin_token=_ADMIN, inference_token=_INFERENCE),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {
        "messages": [{"role": "user", "content": "hello"}],
        "include_orchestration_trace": True,
    }
    try:
        status, body = post(f"http://127.0.0.1:{port}/v1/chat/completions", payload, _INFERENCE)
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200
    assert "trace" not in body.get("orchestration", {})
    # String "false" must not become truthy if coercion is ever allowed.
    status2, body2 = 0, {}
    server2 = build_server(
        orch,
        port=0,
        security=SecurityConfig(admin_token=_ADMIN, inference_token=_INFERENCE),
    )
    t2 = threading.Thread(target=server2.serve_forever, daemon=True)
    t2.start()
    port2 = server2.server_address[1]
    try:
        status2, body2 = post(
            f"http://127.0.0.1:{port2}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hello"}], "include_orchestration_trace": "false"},
            _INFERENCE,
        )
    finally:
        server2.shutdown()
        t2.join(timeout=5)
    assert status2 == 400
    assert body2["error_code"] == "invalid_boolean"


def test_admin_token_can_request_orchestration_trace_on_admin_surfaces() -> None:
    """Admin simulate path may include traces; inference chat remains answer-only."""
    orch = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])
    security = SecurityConfig(
        admin_token=_ADMIN,
        inference_token=_INFERENCE,
        expose_trace_by_default=True,
        trace_authority_secret="trace_authority_secret_123",
    )
    credential = security.issue_trace_credential(
        tenant="tenant_a",
        resource="/admin/simulate",
        purpose="orchestration_trace",
        expires_at=int(time.time()) + 60,
    )
    server = build_server(
        orch,
        port=0,
        security=security,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        # Admin simulate is admin-scoped and may carry traces when requested.
        status, body = post(
            f"http://127.0.0.1:{port}/admin/simulate",
            {"prompt": "hello", "mode": "route", "include_orchestration_trace": True},
            _ADMIN,
            {"x-trace-authority": credential, "x-tenant-id": "tenant_a"},
        )
        assert status == 200
        assert body.get("trace")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_single_token_mode_trace_requires_explicit_true_bool() -> None:
    orch = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])
    server = build_server(
        orch,
        port=0,
        security=SecurityConfig(auth_token=_SINGLE, expose_trace_by_default=False),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hello"}], "include_orchestration_trace": True},
            _SINGLE,
        )
        # Single-token deployments still require the separate trace credential.
        assert status == 200
        # A bearer token alone is never trace authority.
        assert "trace" not in body.get("orchestration", {})
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_trace_credential_rejects_revoked_claims() -> None:
    security = SecurityConfig(
        auth_token=_SINGLE,
        trace_authority_secret="trace_authority_secret_123",
        revoked_trace_credential_ids=("revoked_id",),
    )
    credential = security.issue_trace_credential(
        tenant="tenant_a",
        resource="/v1/chat/completions",
        purpose="orchestration_trace",
        expires_at=int(time.time()) + 60,
        credential_id="revoked_id",
    )
    headers = {"x-trace-authority": credential, "x-tenant-id": "tenant_a"}
    assert not security.may_disclose_trace(headers, "inference", "/v1/chat/completions")


if __name__ == "__main__":
    test_inference_token_cannot_obtain_orchestration_trace()
    test_admin_token_can_request_orchestration_trace_on_admin_surfaces()
    test_single_token_mode_trace_requires_explicit_true_bool()
    test_trace_credential_rejects_revoked_claims()
    print("ok")
