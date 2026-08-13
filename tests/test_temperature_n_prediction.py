"""OpenAI temperature, n, and prediction shape validation on chat completions."""

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
    _validate_n_choices,
    _validate_prediction,
    _validate_temperature,
    build_server,
)

_TEST_AUTH_TOKEN = "temp_n_pred_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_temperature() -> None:
    assert _validate_temperature({}) is None
    assert _validate_temperature({"temperature": 0.7}) == 0.7
    assert _validate_temperature({"temperature": 0}) == 0.0
    assert _validate_temperature({"temperature": 2}) == 2.0
    try:
        _validate_temperature({"temperature": 2.5})
        raise AssertionError("range")
    except RequestError as exc:
        assert exc.code == "invalid_temperature"
    try:
        _validate_temperature({"temperature": True})
        raise AssertionError("bool")
    except RequestError as exc:
        assert exc.code == "invalid_temperature"


def test_validate_n_choices() -> None:
    assert _validate_n_choices({}) is None
    assert _validate_n_choices({"n": 1}) == 1
    try:
        _validate_n_choices({"n": 2})
        raise AssertionError("n!=1")
    except RequestError as exc:
        assert exc.code == "invalid_n"
    try:
        _validate_n_choices({"n": 1.0})
        raise AssertionError("float")
    except RequestError as exc:
        assert exc.code == "invalid_n"


def test_validate_prediction() -> None:
    assert _validate_prediction({}) is None
    assert _validate_prediction({"prediction": {"type": "content", "content": "hello"}})["type"] == "content"
    parts = {
        "type": "content",
        "content": [{"type": "text", "text": "predicted"}],
    }
    assert _validate_prediction({"prediction": parts}) == parts
    try:
        _validate_prediction({"prediction": "raw"})
        raise AssertionError("non-object")
    except RequestError as exc:
        assert exc.code == "invalid_prediction"
    try:
        _validate_prediction({"prediction": {"type": "embedding", "content": "x"}})
        raise AssertionError("type")
    except RequestError as exc:
        assert exc.code == "invalid_prediction"
    try:
        _validate_prediction({"prediction": {"type": "content", "content": ""}})
        raise AssertionError("empty")
    except RequestError as exc:
        assert exc.code == "invalid_prediction"
    try:
        _validate_prediction(
            {"prediction": {"type": "content", "content": [{"type": "image", "text": "x"}]}}
        )
        raise AssertionError("part type")
    except RequestError as exc:
        assert exc.code == "invalid_prediction"


def test_http_temperature_and_n_accepted() -> None:
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
                    "temperature": 0.4,
                    "n": 1,
                    "prediction": {"type": "content", "content": "hello world"},
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


def test_http_n_not_one_rejected() -> None:
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
                    "n": 3,
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
            assert body["error"]["code"] == "invalid_n"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_temperature_out_of_range_rejected() -> None:
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
                    "temperature": 3,
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
            assert body["error"]["code"] == "invalid_temperature"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_temperature()
    test_validate_n_choices()
    test_validate_prediction()
    test_http_temperature_and_n_accepted()
    test_http_n_not_one_rejected()
    test_http_temperature_out_of_range_rejected()
    print("ok")
