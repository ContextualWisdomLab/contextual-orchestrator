"""Known OpenAI modality paths return 501 not_implemented (not 404)."""

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

_TEST_AUTH_TOKEN = "not_impl_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _request(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
        "connection": "close",
    }
    if payload is not None:
        headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_images_generations_returns_501_not_404() -> None:
    """Buyer path: image clients get an explicit not-implemented, not a generic 404."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _request(
            "POST",
            f"http://127.0.0.1:{port}/v1/images/generations",
            {"prompt": "a red cube", "n": 1},
        )
        unknown_status, unknown_body = _request(
            "POST",
            f"http://127.0.0.1:{port}/v1/totally-unknown-endpoint",
            {"x": 1},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 501, body
    assert body["error"]["code"] == "not_implemented"
    assert "/v1/images/generations" in body["error"]["message"]
    assert unknown_status == 404
    assert unknown_body["error"]["code"] == "route_not_found"


def test_audio_and_moderations_and_files_return_501() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    paths = [
        ("POST", "/v1/audio/transcriptions", {"model": "whisper-1"}),
        ("POST", "/v1/audio/speech", {"input": "hi", "voice": "alloy"}),
        ("POST", "/v1/moderations", {"input": "hello"}),
        ("GET", "/v1/files", None),
        ("GET", "/v1/files/file_abc", None),
    ]
    try:
        for method, path, payload in paths:
            status, body = _request(method, f"http://127.0.0.1:{port}{path}", payload)
            assert status == 501, (path, body)
            assert body["error"]["code"] == "not_implemented", path
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_chat_completions_still_works() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _request(
            "POST",
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}], "orchestration": "route"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert body["object"] == "chat.completion"




def test_assistants_vector_stores_and_openai_batches_return_501() -> None:
    """Buyer path: Assistants/Threads/Vector Stores/Batches SDKs get 501 not 404."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    paths = [
        ("GET", "/v1/assistants", None),
        ("POST", "/v1/assistants", {"model": "gpt-4o", "name": "helper"}),
        ("GET", "/v1/assistants/asst_abc", None),
        ("POST", "/v1/threads", {}),
        ("GET", "/v1/threads/thread_abc", None),
        ("GET", "/v1/vector_stores", None),
        ("POST", "/v1/vector_stores", {"name": "kb"}),
        ("GET", "/v1/vector_stores/vs_abc", None),
        ("GET", "/v1/batches", None),
        ("POST", "/v1/batches", {"input_file_id": "file_abc", "endpoint": "/v1/chat/completions"}),
        ("GET", "/v1/batches/batch_abc", None),
    ]
    try:
        for method, path, payload in paths:
            status, body = _request(method, f"http://127.0.0.1:{port}{path}", payload)
            assert status == 501, (path, body)
            assert body["error"]["code"] == "not_implemented", path
    finally:
        server.shutdown()
        thread.join(timeout=5)

if __name__ == "__main__":
    test_images_generations_returns_501_not_404()
    test_audio_and_moderations_and_files_return_501()
    test_assistants_vector_stores_and_openai_batches_return_501()
    test_chat_completions_still_works()
    print("ok")
