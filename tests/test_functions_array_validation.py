"""Legacy OpenAI functions array shape validation on chat completions."""

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
    _validate_functions,
    build_server,
)

_TEST_AUTH_TOKEN = "functions_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _sample_functions() -> list[dict]:
    return [
        {
            "name": "get_weather",
            "description": "Current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]


def test_validate_functions() -> None:
    assert _validate_functions({}) is None
    fns = _sample_functions()
    assert _validate_functions({"functions": fns}) == fns
    try:
        _validate_functions({"functions": []})
        raise AssertionError("expected empty reject")
    except RequestError as exc:
        assert exc.code == "invalid_functions"
    try:
        _validate_functions({"functions": [{"name": ""}]})
        raise AssertionError("expected name reject")
    except RequestError as exc:
        assert exc.code == "invalid_functions"
    try:
        _validate_functions({"functions": [{"name": "x", "parameters": []}]})
        raise AssertionError("expected parameters reject")
    except RequestError as exc:
        assert exc.code == "invalid_functions"


def test_http_functions_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "weather in seoul"}],
                    "functions": _sample_functions(),
                    "function_call": "auto",
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


def test_http_invalid_functions_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "functions": [{"description": "no name"}],
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
            assert body["error"]["code"] == "invalid_functions"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_functions()
    test_http_functions_accepted()
    test_http_invalid_functions_rejected()
    print("ok")
