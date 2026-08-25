"""Capability endpoints route operator-defined model groups across every modality."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server

TOKEN = "multimodal_group_token"


def _post(port: int, path: str, payload: dict) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read(), response.headers.get_content_type()


@pytest.mark.parametrize(
    ("path", "capability", "payload"),
    [
        ("/v1/images/generations", "image", {"prompt": "an accessible control panel"}),
        ("/v1/videos", "video", {"prompt": "a short product walkthrough"}),
        (
            "/v1/audio/transcriptions",
            "transcription",
            {"input_audio": {"data": "UklGRg==", "format": "wav"}},
        ),
        ("/v1/rerank", "rerank", {"query": "relevant", "documents": ["first", "second"]}),
        (
            "/v1/audio/generations",
            "audio",
            {"messages": [{"role": "user", "content": "make an alert sound"}]},
        ),
    ],
)
def test_json_capability_endpoints_use_measured_group_member(
    path: str, capability: str, payload: dict
) -> None:
    first = ModelAgent("first_member", "provider/first", tags=(capability,), group_name="media_group")
    second = ModelAgent("second_member", "provider/second", tags=(capability,), group_name="media_group")
    orchestrator = TaskOrchestrator([first, second])
    orchestrator._group_router.observe_failure(first.id)
    orchestrator._group_router.observe_success(second.id, 0.1)
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, raw, content_type = _post(
            server.server_address[1], path, {"model": "media-group", **payload}
        )
        assert status == 200 and content_type == "application/json"
        assert json.loads(raw)["model"] == "provider/second"
    finally:
        server.shutdown()


def test_speech_endpoint_preserves_binary_media_response() -> None:
    agent = ModelAgent("speech_member", "provider/speech", tags=("speech",), group_name="speech_group")
    server = build_server(TaskOrchestrator([agent]), port=0, security=SecurityConfig(auth_token=TOKEN))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, raw, content_type = _post(
            server.server_address[1],
            "/v1/audio/speech",
            {"model": "speech-group", "input": "hello", "voice": "alloy"},
        )
        assert status == 200 and content_type == "audio/mpeg" and raw == b"mock audio"
    finally:
        server.shutdown()


def test_openrouter_image_alias_uses_its_dedicated_images_endpoint() -> None:
    agent = ModelAgent(
        "image_member",
        "provider/image",
        tags=("image",),
        group_name="image_group",
        provider_name="openrouter",
    )
    orchestrator = TaskOrchestrator([agent])
    observed: list[str] = []

    def send(_agent: ModelAgent, endpoint: str, payload: dict) -> dict:
        observed.append(endpoint)
        return {"model": payload["model"], "data": []}

    orchestrator.client.proxy_send = send  # type: ignore[method-assign]
    orchestrator.proxy_capability(
        {"model": "image-group", "prompt": "diagram"},
        capability="image",
        endpoint="images/generations",
    )

    assert observed == ["images"]
