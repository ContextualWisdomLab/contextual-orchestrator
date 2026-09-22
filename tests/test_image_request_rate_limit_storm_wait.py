"""An image-bearing request waits out a rate-limit storm like a text request.

``_invoke`` runs an image request on the text candidates when no candidate for
the step is vision-capable. The storm-wait admission recomputed the vision-only
set, found it empty, and failed the whole conduct request at once with 429,
while the same storm on a text request is waited out. The admission must judge
the storm on the candidates ``_invoke`` actually used.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TOKEN = "image_request_storm_wait_token"  # noqa: S105
_STORM_SECONDS = 1.5
_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
_TEXT_TAGS = ("cost:free", "verification", "review", "reasoning", "writing", "planning", "coding", "input:text", "output:text")
_VISION_TAGS = ("cost:free", "reasoning", "writing", "planning", "coding", "vision", "input:image", "input:text", "output:text")


class _Response:
    """Minimal provider response returned by the patched transport."""

    status = 200

    def __init__(self, content: str) -> None:
        self._body = json.dumps(
            {
                "id": "chatcmpl_storm",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        self.headers: dict[str, str] = {}

    def read(self, amount: int | None = None) -> bytes:
        body, self._body = self._body, b""
        return body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return default

    def close(self) -> None:
        self._body = b""

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def _conduct(monkeypatch, *, with_image: bool) -> tuple[int, float]:
    """Run one conduct request while the text-only models are in a 429 storm."""
    set_backend(InMemoryCredentialBackend())
    register_credential("NVIDIA_NIM_API_KEY", "synthetic-not-a-key")
    started = time.monotonic()

    def storm_open(self, request, destination=None, *, timeout=None):
        payload = json.loads(request.data)
        if payload["model"].startswith("vendor/text-") and time.monotonic() - started < _STORM_SECONDS:
            raise urllib.error.HTTPError(
                request.full_url, 429, "Too Many Requests", {"Retry-After": "2"}, io.BytesIO(b'{"error":{"message":"rate limited"}}')
            )
        system = (payload.get("messages") or [{}])[0].get("content", "")
        if system == TaskOrchestrator.TRIAGE_SYSTEM_PROMPT:
            return _Response('{"workflow_required": true}')
        return _Response("PASS: evidence reviewed; the change is consistent.")

    monkeypatch.setattr(ModelClient, "_validate_provider", lambda self, agent: None)
    monkeypatch.setattr(ModelClient, "_open_provider", storm_open)
    agents = [
        ModelAgent("vision_worker", "vendor/vision", base_url="https://provider.invalid/v1",
                   api_key_env="NVIDIA_NIM_API_KEY", tags=_VISION_TAGS, priority=30),
        ModelAgent("text_a", "vendor/text-a", base_url="https://provider.invalid/v1",
                   api_key_env="NVIDIA_NIM_API_KEY", tags=_TEXT_TAGS, priority=10),
        ModelAgent("text_b", "vendor/text-b", base_url="https://provider.invalid/v1",
                   api_key_env="NVIDIA_NIM_API_KEY", tags=_TEXT_TAGS, priority=5),
    ]
    content: list[dict] = [{"type": "text", "text": "Review this change set in depth: plan, implement, verify."}]
    if with_image:
        content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + _PNG}})
    server = build_server(TaskOrchestrator(agents), port=0, security=SecurityConfig(auth_token=_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
        data=json.dumps({"model": TaskOrchestrator.FREE_MODEL, "mode": "conduct", "messages": [{"role": "user", "content": content}]}).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {_TOKEN}", "connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        with exc:
            exc.read()
            status = exc.code
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        set_backend(None)
    return status, time.monotonic() - started


@pytest.mark.parametrize("with_image", [False, True], ids=["text", "image"])
def test_rate_limit_storm_on_the_used_candidates_is_waited_out(monkeypatch, with_image) -> None:
    """Both request shapes wait for the provider cooldown and then succeed."""
    status, elapsed = _conduct(monkeypatch, with_image=with_image)

    assert status == 200
    assert elapsed >= _STORM_SECONDS
