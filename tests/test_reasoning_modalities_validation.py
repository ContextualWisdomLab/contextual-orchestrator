"""OpenAI reasoning_effort enum and modalities list validation."""

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
    _validate_modalities,
    _validate_reasoning_effort,
    build_server,
)

_TEST_AUTH_TOKEN = "reason_mod_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_reasoning_effort() -> None:
    assert _validate_reasoning_effort({}) is None
    assert _validate_reasoning_effort({"reasoning_effort": "high"}) == "high"
    assert _validate_reasoning_effort({"reasoning_effort": "minimal"}) == "minimal"
    try:
        _validate_reasoning_effort({"reasoning_effort": "extreme"})
        raise AssertionError("bad enum")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning_effort"
    try:
        _validate_reasoning_effort({"reasoning_effort": 1})
        raise AssertionError("non-string")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning_effort"


def test_validate_modalities() -> None:
    assert _validate_modalities({}) is None
    assert _validate_modalities({"modalities": ["text"]}) == ["text"]
    assert _validate_modalities({"modalities": ["text", "audio"]}) == ["text", "audio"]
    try:
        _validate_modalities({"modalities": []})
        raise AssertionError("empty")
    except RequestError as exc:
        assert exc.code == "invalid_modalities"
    try:
        _validate_modalities({"modalities": ["video"]})
        raise AssertionError("video")
    except RequestError as exc:
        assert exc.code == "invalid_modalities"
    try:
        _validate_modalities({"modalities": "text"})
        raise AssertionError("non-list")
    except RequestError as exc:
        assert exc.code == "invalid_modalities"


def test_http_reasoning_and_modalities_accepted() -> None:
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
                    "reasoning_effort": "medium",
                    "modalities": ["text"],
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


def test_http_invalid_reasoning_effort_rejected() -> None:
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
                    "reasoning_effort": "ultra",
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
            assert body["error"]["code"] == "invalid_reasoning_effort"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_invalid_modalities_rejected() -> None:
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
                    "modalities": ["image"],
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
            assert body["error"]["code"] == "invalid_modalities"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_reasoning_effort()
    test_validate_modalities()
    test_http_reasoning_and_modalities_accepted()
    test_http_invalid_reasoning_effort_rejected()
    test_http_invalid_modalities_rejected()
    print("ok")
