"""openai-processing-ms latency header on API responses."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "secret_token"  # noqa: S105


def test_chat_and_healthz_include_openai_processing_ms() -> None:
    """Buyer ops can measure server-side latency without body parsing."""
    server = build_server(
        TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            ms = response.headers.get("openai-processing-ms") or response.headers.get("OpenAI-Processing-Ms")
            assert ms is not None and int(ms) >= 0

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200
            ms = response.headers.get("openai-processing-ms") or response.headers.get("OpenAI-Processing-Ms")
            assert ms is not None and int(ms) >= 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_chat_and_healthz_include_openai_processing_ms()
    print("ok")
