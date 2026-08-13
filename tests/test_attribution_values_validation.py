"""Attribution dimension value shape validation for cost ledger keys."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_attribution,
    build_server,
)

_TEST_AUTH_TOKEN = "attr_val_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_attribution_values() -> None:
    assert _validate_attribution(None) is None
    assert _validate_attribution({"team": "platform", "service": "gateway"}) == {
        "team": "platform",
        "service": "gateway",
    }
    assert _validate_attribution({"team": 42}) == {"team": "42"}
    try:
        _validate_attribution({"team": ""})
        raise AssertionError("empty")
    except RequestError as exc:
        assert exc.code == "invalid_attribution"
    try:
        _validate_attribution({"team": "  "})
        raise AssertionError("blank")
    except RequestError as exc:
        assert exc.code == "invalid_attribution"
    try:
        _validate_attribution({"team": True})
        raise AssertionError("bool")
    except RequestError as exc:
        assert exc.code == "invalid_attribution"
    try:
        _validate_attribution({"not_a_dimension": "x"})
        raise AssertionError("unknown")
    except RequestError as exc:
        assert exc.code == "invalid_attribution"


def test_http_attribution_accepted() -> None:
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
                    "attribution": {"team": "buyer_ops", "service": "chat_gateway"},
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
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert body["object"] == "chat.completion"


def test_http_empty_attribution_value_rejected() -> None:
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
                    "attribution": {"team": ""},
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_attribution"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_attribution_values()
    test_http_attribution_accepted()
    test_http_empty_attribution_value_rejected()
    print("ok")
