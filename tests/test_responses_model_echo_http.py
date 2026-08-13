"""HTTP honesty: Responses passthrough echoes request model on the response body."""

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

_TEST_AUTH_TOKEN = "responses_model_echo_token"  # noqa: S105


def _serve():
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "coding", "writing"),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _post(port: int, payload: dict) -> tuple[int, dict]:
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
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_responses_echoes_request_model() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {"model": "buyer-deployment-xyz", "input": "summarize the invoice"},
        )
        assert status == 200, body
        assert body.get("object") == "response", body
        assert body.get("model") == "buyer-deployment-xyz", body
        # Must not silently rewrite to the internal agent model id.
        assert body.get("model") != "mock-a", body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_model_echo_with_instructions() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "buyer-with-instructions",
                "input": "hello",
                "instructions": "Be concise.",
            },
        )
        assert status == 200, body
        assert body.get("model") == "buyer-with-instructions", body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_missing_model_rejected() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(port, {"input": "no model field"})
        assert status == 400, body
        assert body.get("error", {}).get("code") == "invalid_model", body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_empty_model_rejected() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(port, {"model": "  ", "input": "blank model"})
        assert status == 400, body
        assert body.get("error", {}).get("code") == "invalid_model", body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_object_shape_preserved() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {"model": "shape-check-model", "input": ["item-one"]},
        )
        assert status == 200, body
        assert body.get("object") == "response", body
        assert body.get("model") == "shape-check-model", body
        assert isinstance(body.get("output"), list), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_echoes_request_model()
    test_http_responses_model_echo_with_instructions()
    test_http_responses_missing_model_rejected()
    test_http_responses_empty_model_rejected()
    test_http_responses_object_shape_preserved()
    print("ok")
