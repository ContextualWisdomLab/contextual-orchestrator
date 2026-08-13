"""Non-empty user/system content and OpenAI metadata map validation."""

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
    _validate_messages,
    _validate_openai_metadata,
    build_server,
)

_TEST_AUTH_TOKEN = "content_meta_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_messages_rejects_empty_user_system_content() -> None:
    assert _validate_messages([{"role": "user", "content": "ok"}])[0]["content"] == "ok"
    try:
        _validate_messages([{"role": "user", "content": "  "}])
        raise AssertionError("empty user")
    except RequestError as exc:
        assert exc.code == "invalid_message"
    try:
        _validate_messages([{"role": "system", "content": ""}])
        raise AssertionError("empty system")
    except RequestError as exc:
        assert exc.code == "invalid_message"
    # assistant empty remains allowed (tool_calls-style turns)
    rows = _validate_messages(
        [
            {"role": "user", "content": "call tool"},
            {"role": "assistant", "content": ""},
        ]
    )
    assert rows[1]["content"] == ""


def test_validate_openai_metadata() -> None:
    assert _validate_openai_metadata(None) is None
    assert _validate_openai_metadata({"trace_id": "abc", "team": "ops"}) == {
        "trace_id": "abc",
        "team": "ops",
    }
    try:
        _validate_openai_metadata(["nope"])
        raise AssertionError("list")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
    try:
        _validate_openai_metadata({"n": 1})
        raise AssertionError("non-string value")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
    try:
        _validate_openai_metadata({f"k{i}": "v" for i in range(17)})
        raise AssertionError("too many")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"


def test_http_metadata_accepted_and_invalid_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        good = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "orchestration": "route",
                    "metadata": {"trace_id": "run-1", "buyer": "acme"},
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(good, timeout=5) as response:
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
        assert body["object"] == "chat.completion"

        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "metadata": {"count": 3},
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
            urllib.request.urlopen(bad, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            bad_body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert bad_body["error"]["code"] == "invalid_metadata"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_empty_user_content_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": ""}]}).encode("utf-8"),
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
            assert body["error"]["code"] == "invalid_message"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_messages_rejects_empty_user_system_content()
    test_validate_openai_metadata()
    test_http_metadata_accepted_and_invalid_rejected()
    test_http_empty_user_content_rejected()
    print("ok")
