"""Whitespace-padded service_tier auto/default and encoding_format float honesty."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "service_tier_encoding_format_strip_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    orchestrator = build()
    counter = type("ExactSyntheticCounter", (), {"count_text": lambda self, text, model="": len(text)})()
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
        coordinator=CostRoutingCoordinator(orchestrator, embedding_token_counter=counter),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_padded_service_tier_auto() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tier pad"}],
                "service_tier": " auto ",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_padded_service_tier_default() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tier default pad"}],
                "service_tier": "\tdefault\n",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_padded_service_tier_default() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "tier completions pad",
                "service_tier": " default ",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_padded_service_tier_auto() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "tier responses pad",
                "service_tier": "\tauto\t",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_padded_flex_service_tier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tier flex"}],
                "service_tier": " flex ",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_padded_encoding_format_float() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "encode pad float",
                "encoding_format": " float ",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_padded_base64() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "encode pad base64",
                "encoding_format": " base64 ",
            },
        )
        assert status == 200, body
        data = body.get("data") or []
        assert data and isinstance(data[0].get("embedding"), str), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_padded_service_tier_auto()
    test_http_chat_accepts_padded_service_tier_default()
    test_http_completions_accepts_padded_service_tier_default()
    test_http_responses_accepts_padded_service_tier_auto()
    test_http_chat_accepts_padded_flex_service_tier()
    test_http_embeddings_accepts_padded_encoding_format_float()
    test_http_embeddings_accepts_padded_base64()
    print("ok")
