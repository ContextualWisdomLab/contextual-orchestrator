"""X-Request-Id correlation header on API responses."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "secret_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_success_and_error_responses_include_x_request_id() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        # Unauthenticated error still carries a correlation id.
        err_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/healthz",
            headers={"connection": "close"},
        )
        with urllib.request.urlopen(err_req, timeout=5) as response:
            assert response.status == 200
            health_rid = response.headers.get("X-Request-Id") or response.headers.get("x-request-id")
            assert health_rid and len(health_rid) >= 16

        ok_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(ok_req, timeout=5) as response:
            assert response.status == 200
            ok_rid = response.headers.get("X-Request-Id") or response.headers.get("x-request-id")
            assert ok_rid and len(ok_rid) >= 16

        bad_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={"content-type": "application/json", "connection": "close"},
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_req, timeout=5)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            err_rid = exc.headers.get("X-Request-Id") or exc.headers.get("x-request-id")
            body = json.loads(exc.read().decode("utf-8"))
            assert err_rid and len(err_rid) >= 16
            # Error JSON request_id matches header when present.
            assert body["error"]["detail"]["request_id"] == err_rid
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_success_and_error_responses_include_x_request_id()
    print("ok")
