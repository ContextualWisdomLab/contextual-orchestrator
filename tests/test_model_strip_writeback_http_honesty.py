"""Model strip writeback so tools/Responses passthrough bind padded names."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    _validate_completions_model,
    _validate_embeddings_model,
    _validate_responses_model,
    build_server,
)

_TEST_AUTH_TOKEN = "model_strip_writeback_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
    )


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


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_unit_model_strip_writeback() -> None:
    for validate in (
        _validate_completions_model,
        _validate_responses_model,
        _validate_embeddings_model,
    ):
        body: dict = {"model": "  mock-planner  "}
        assert validate(body) == "mock-planner"
        assert body["model"] == "mock-planner"


def test_unit_model_rejects_blank() -> None:
    for validate in (
        _validate_completions_model,
        _validate_responses_model,
        _validate_embeddings_model,
    ):
        try:
            validate({"model": "   "})
            raise AssertionError("expected RequestError")
        except Exception as exc:  # noqa: BLE001 — assert named code
            assert getattr(exc, "code", None) == "invalid_model"


def test_http_chat_tools_accepts_padded_model() -> None:
    """Tools passthrough uses body.model for pool match — must see strip writeback."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "  mock-planner  ",
                "messages": [{"role": "user", "content": "tools pad model"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_item",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_advertised_gateway_default_model() -> None:
    """The gateway-default id advertised on /v1/models must be callable on chat.

    Regression: ``_require_pool_model`` special-cased only
    :data:`TaskOrchestrator.AUTO_MODEL`/:data:`TaskOrchestrator.FREE_MODEL`,
    so the first entry of the advertised model list — the literal
    ``contextual-orchestrator`` default every batch request already used —
    was rejected with 400 on the general chat surface. Callers could submit
    batch jobs but never hold a conversation: the endpoint contract matched
    the async batch-routing API only.
    """
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": TaskOrchestrator.GATEWAY_DEFAULT_MODEL,
                "messages": [{"role": "user", "content": "gateway default chat"}],
            },
        )
        assert status == 200, body
        assert body["model"] == TaskOrchestrator.GATEWAY_DEFAULT_MODEL

        # The advertised list must keep offering exactly this id first.
        models_request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/models",
            headers={"authorization": f"Bearer {_TEST_AUTH_TOKEN}"},
        )
        with urllib.request.urlopen(models_request, timeout=10) as response:
            listed = json.loads(response.read().decode("utf-8"))
        assert listed["data"][0]["id"] == TaskOrchestrator.GATEWAY_DEFAULT_MODEL
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("stream", [False, True])
def test_http_responses_accepts_advertised_gateway_default_model(stream: bool) -> None:
    """Responses must share the advertised gateway-default virtual model contract."""
    server, thread, port = _server()
    try:
        payload = {
            "model": TaskOrchestrator.GATEWAY_DEFAULT_MODEL,
            "input": "gateway default responses",
            "stream": stream,
        }
        if stream:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/responses",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                    "connection": "close",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
                assert response.headers.get_content_type() == "text/event-stream"
                assert b"response.completed" in response.read()
        else:
            status, body = _post(port, "/v1/responses", payload)
            assert status == 200, body
            assert body["model"] == TaskOrchestrator.GATEWAY_DEFAULT_MODEL
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_response_format_accepts_padded_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": " mock-planner ",
                "messages": [{"role": "user", "content": "rf pad model"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_padded_model() -> None:
    server, thread, port = _server()
    try:
        for model in (" mock-planner ", "  mock-planner  ", "\tmock-planner\n"):
            status, body = _post(
                port,
                "/v1/responses",
                {"model": model, "input": f"resp pad {model!r}"},
            )
            assert status == 200, (model, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_tools_accepts_padded_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "  mock-planner  ",
                "input": "resp tools pad model",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup_item",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_padded_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "  mock-planner  ", "prompt": "legacy pad model"},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_unknown_padded_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "  no-such-model  ",
                "messages": [{"role": "user", "content": "unknown"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_item",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_request" in blob or "not available" in blob
        assert "no-such-model" in blob
        # Must not echo leading pad after strip (buyer sees real id).
        assert "'  no-such-model  '" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_unit_model_strip_writeback()
    test_unit_model_rejects_blank()
    test_http_chat_tools_accepts_padded_model()
    test_http_chat_response_format_accepts_padded_model()
    test_http_responses_accepts_padded_model()
    test_http_responses_tools_accepts_padded_model()
    test_http_completions_accepts_padded_model()
    test_http_chat_still_rejects_unknown_padded_model()
    print("ok")
