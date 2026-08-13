"""OpenAI-compatible fail-closed model resolution for unknown model ids."""

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
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing")),
            ModelAgent("coding_agent", "mock-coder", tags=("coding",)),
        ]
    )


def post_json(url: str, payload: dict[str, object], token: str = _TEST_AUTH_TOKEN) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_resolve_request_model_accepts_gateway_default_and_pool_models() -> None:
    orchestrator = build()
    assert orchestrator.resolve_request_model(None) == "contextual-orchestrator"
    assert orchestrator.resolve_request_model("contextual-orchestrator") == "contextual-orchestrator"
    assert orchestrator.resolve_request_model("mock-coder") == "mock-coder"
    try:
        orchestrator.resolve_request_model("gpt-not-in-pool")
        raise AssertionError("expected KeyError")
    except KeyError as exc:
        assert str(exc.args[0]) == "gpt-not-in-pool"


def test_chat_completions_returns_404_for_unknown_model() -> None:
    """Buyer path: OpenAI clients get model_not_found instead of silent mis-route."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        ok_status, ok_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hello"}],
                "orchestration": "route",
            },
        )
        bad_status, bad_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {
                "model": "definitely-not-a-pool-model",
                "messages": [{"role": "user", "content": "hello"}],
                "orchestration": "route",
            },
        )
        default_status, _ = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hello"}], "orchestration": "route"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert ok_status == 200
    assert ok_body["model"] == "mock-generalist"
    assert bad_status == 404
    assert bad_body["error"]["code"] == "model_not_found"
    assert default_status == 200


def test_embeddings_batch_returns_404_for_unknown_model() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/batch/embeddings",
            {"model": "nope-model", "input": ["alpha"]},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 404
    assert body["error"]["code"] == "model_not_found"


if __name__ == "__main__":
    test_resolve_request_model_accepts_gateway_default_and_pool_models()
    test_chat_completions_returns_404_for_unknown_model()
    test_embeddings_batch_returns_404_for_unknown_model()
    print("ok")
