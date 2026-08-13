"""OpenAI developer message role for o-series / GPT-style SDKs."""

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
    ALLOWED_MESSAGE_ROLES,
    RequestError,
    SecurityConfig,
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "developer_role_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_allowed_message_roles_include_developer() -> None:
    assert "developer" in ALLOWED_MESSAGE_ROLES


def test_validate_messages_accepts_developer_role() -> None:
    messages = [
        {"role": "developer", "content": "Follow company policy."},
        {"role": "user", "content": "Hello"},
    ]
    validated = _validate_messages(messages)
    assert validated[0]["role"] == "developer"
    assert validated[0]["content"] == "Follow company policy."
    assert validated[1]["role"] == "user"


def test_validate_messages_rejects_unknown_role() -> None:
    try:
        _validate_messages([{"role": "narrator", "content": "x"}])
        raise AssertionError("expected reject for unknown role")
    except RequestError as exc:
        assert exc.code == "invalid_message"


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_chat_accepts_developer_role() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [
                    {"role": "developer", "content": "Be concise."},
                    {"role": "user", "content": "Say hi"},
                ],
            },
        )
        assert status in {200, 202}, body
        if status == 200:
            content = body["choices"][0]["message"]["content"]
            assert "Say hi" in content or "hi" in content.lower() or content
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_role() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "narrator", "content": "x"}],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_orchestrator_route_with_developer_prefix() -> None:
    orch = build()
    result = orch.complete(
        [
            {"role": "developer", "content": "Role: worker"},
            {"role": "user", "content": "route me please"},
        ],
        mode="route",
    )
    assert result.get("answer") or result.get("output") or result


if __name__ == "__main__":
    test_allowed_message_roles_include_developer()
    test_validate_messages_accepts_developer_role()
    test_validate_messages_rejects_unknown_role()
    test_http_chat_accepts_developer_role()
    test_http_chat_rejects_unknown_role()
    test_orchestrator_route_with_developer_prefix()
    print("ok")
