"""Gateway GET /v1/models lists the composed catalog (not only a facade name)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def test_v1_models_lists_facade_and_pool_models() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("openai_mini", "gpt-4o-mini", tags=("reasoning",), provider_name="openai"),
            ModelAgent("nvidia_kimi", "moonshotai/kimi-k2.5", tags=("reasoning",), provider_name="nvidia_nim"),
        ]
    )
    token = "models_token"
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/models",
            headers={"authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert body["object"] == "list"
    ids = [row["id"] for row in body["data"]]
    assert "contextual-orchestrator" in ids
    assert "gpt-4o-mini" in ids
    assert "moonshotai/kimi-k2.5" in ids


def test_v1_models_requires_inference_auth() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("solo_worker", "mock-model", tags=("reasoning",))])
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        raised = False
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=5)
        except urllib.error.HTTPError as exc:
            raised = True
            assert exc.code in {401, 403}
        assert raised
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/models",
            headers={"authorization": "Bearer inference_secret"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        assert body["object"] == "list"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_v1_models_lists_facade_and_pool_models()
    test_v1_models_requires_inference_auth()
    print("ok")
