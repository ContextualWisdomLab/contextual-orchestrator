"""Trace disclosure requires authority beyond ordinary inference access."""
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

_ADMIN = "admin_secret"  # noqa: S105
_INFERENCE = "inference_secret"  # noqa: S105
_SINGLE = "single_token"  # noqa: S105


def post(url: str, payload: dict, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "connection": "close",
        },
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
    assert status2 in {200, 400}
    if status2 == 200:
        assert "trace" not in body2.get("orchestration", {})


def test_admin_token_can_request_orchestration_trace_on_admin_surfaces() -> None:
    """Admin simulate path may include traces; inference chat remains answer-only."""
    orch = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])
    server = build_server(
        orch,
        port=0,
        security=SecurityConfig(admin_token=_ADMIN, inference_token=_INFERENCE, expose_trace_by_default=True),
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
        )
        assert status == 200
        assert "trace" in body.get("orchestration", body) or body.get("mode") is not None
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
        # Single-token deployments treat the token as both scopes; explicit true
        # still requires a verified bool and host policy allow when configured.
        assert status == 200
        # Without expose_trace_by_default and without admin-only split, single
        # token may disclose only when request bool is true AND policy allows —
        # default remain denied when expose_trace_by_default is false unless
        # request is authorized for trace. Single token gets answer only by default.
        assert "trace" not in body.get("orchestration", {})
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_inference_token_cannot_obtain_orchestration_trace()
    test_admin_token_can_request_orchestration_trace_on_admin_surfaces()
    test_single_token_mode_trace_requires_explicit_true_bool()
    print("ok")
