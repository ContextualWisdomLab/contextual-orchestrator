"""orchestrator/free image parts must use image-capable free agents or fail closed.

Synthetic DOCX/HWPX figure review sends text + image_url parts on
``orchestrator/free``. A text-only free agent must not absorb that traffic and
return a 200 that silently ignores figures. Coverage is local/mock only — no
research document upload.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server

_TEST_AUTH_TOKEN = "review_free_multimodal_image_failclosed_token"  # noqa: S105

# 1x1 PNG — synthetic figure bytes, not a research artifact.
_TINY_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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
        with exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


def _serve(orchestrator: TaskOrchestrator):
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _figure_payload(*, model: str = TaskOrchestrator.FREE_MODEL) -> dict:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Review table 1 and figure 1 in this synthetic paper excerpt.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": _TINY_PNG_DATA_URI},
                    },
                ],
            }
        ],
    }


def test_free_image_request_fails_closed_when_only_text_free_agents_exist() -> None:
    """Text-only free pool must not succeed on figure-bearing free traffic."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "text_free",
                "mock-text-free",
                tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
                base_url="mock://text",
            )
        ]
    )
    server, thread, port = _serve(orchestrator)
    try:
        status, body = _post(port, _figure_payload())
        assert status == 400, body
        blob = json.dumps(body).casefold()
        assert "input:image" in blob or "required tags" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_free_image_request_serves_image_capable_free_agent() -> None:
    """When a free text+image agent exists, figure-bearing free traffic reaches it."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "text_free",
                "mock-text-free",
                tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
                base_url="mock://text",
            ),
            ModelAgent(
                "vision_free",
                "mock-vision-free",
                tags=(
                    "cost:free",
                    "reasoning",
                    "writing",
                    "input:text",
                    "input:image",
                    "output:text",
                ),
                base_url="mock://vision",
            ),
        ]
    )
    server, thread, port = _serve(orchestrator)
    try:
        status, body = _post(port, _figure_payload())
        assert status == 200, body
        served = body.get("model") or ""
        assert "vision" in served or body.get("choices"), body
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_text_only_free_request_still_excludes_vision_free_agent() -> None:
    """Blind free text traffic must not select a non-text-input free deployment."""
    vision = ModelAgent(
        "vision_free",
        "mock-vision-free",
        tags=(
            "cost:free",
            "reasoning",
            "writing",
            "input:text",
            "input:image",
            "output:text",
        ),
        base_url="mock://vision",
    )
    text = ModelAgent(
        "text_free",
        "mock-text-free",
        tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
        base_url="mock://text",
    )
    orchestrator = TaskOrchestrator([vision, text])
    assert not orchestrator._is_general_free_agent(vision)
    assert orchestrator._is_general_free_agent(text)
    free_text_ids = orchestrator._free_pool_agent_ids(
        messages=[{"role": "user", "content": "text only review"}]
    )
    assert free_text_ids == {"text_free"}
    free_image_ids = orchestrator._free_pool_agent_ids(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "figure"},
                    {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URI}},
                ],
            }
        ]
    )
    assert free_image_ids == {"vision_free"}


if __name__ == "__main__":
    test_free_image_request_fails_closed_when_only_text_free_agents_exist()
    test_free_image_request_serves_image_capable_free_agent()
    test_text_only_free_request_still_excludes_vision_free_agent()
    print("ok")
