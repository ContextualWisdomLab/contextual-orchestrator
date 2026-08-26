"""Capability endpoints route operator-defined model groups across every modality."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient, RequestDeadlineExceeded
from contextual_orchestrator.server import SecurityConfig, build_server

TOKEN = "multimodal_group_token"


def _post(
    port: int, path: str, payload: dict, extra_headers: dict[str, str] | None = None
) -> tuple[int, bytes, str]:
    headers = {"content-type": "application/json", "authorization": f"Bearer {TOKEN}"}
    headers.update(extra_headers or {})
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read(), response.headers.get_content_type()


def _post_error(port: int, path: str, payload: dict) -> tuple[int, dict]:
    try:
        _post(port, path, payload)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())
    raise AssertionError("request unexpectedly succeeded")


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


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/v1/images/generations", {"prompt": "diagram"}),
        ("/v1/audio/speech", {"input": "hello", "voice": "alloy"}),
    ],
)
def test_capability_routes_apply_the_caller_deadline(path: str, payload: dict) -> None:
    capability = "speech" if path.endswith("speech") else "image"
    agent = ModelAgent("media_member", "provider/media", tags=(capability,))
    orchestrator = TaskOrchestrator([agent])
    observed: list[float | None] = []
    original = orchestrator.proxy_capability

    def proxy(*args, **kwargs):
        observed.append(
            orchestrator.client.request_settings_snapshot()["request_deadline_monotonic"]
        )
        return original(*args, **kwargs)

    orchestrator.proxy_capability = proxy  # type: ignore[method-assign]
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, _raw, _content_type = _post(
            server.server_address[1],
            path,
            payload,
            {"x-request-timeout-ms": "180000"},
        )
        assert status == 200
    finally:
        server.shutdown()

    assert len(observed) == 1 and observed[0] is not None


def test_binary_provider_transport_uses_the_remaining_deadline() -> None:
    agent = ModelAgent(
        "speech_member",
        "provider/speech",
        base_url="https://provider.example/v1",
        credential_key="",
    )
    client = ModelClient()
    observed: list[float | None] = []

    class Response:
        headers = type("Headers", (), {"get_content_type": lambda self: "audio/mpeg"})()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"audio"

    def open_provider(_request, _destination=None):
        observed.append(getattr(client._local, "provider_transport_timeout", None))
        return Response()

    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_open_provider", side_effect=open_provider
    ), patch(
        "contextual_orchestrator.orchestrator.time.monotonic", return_value=10.0
    ), client.request_settings(request_deadline_monotonic=15.0):
        assert client.proxy_send_bytes(agent, "audio/speech", {}) == (b"audio", "audio/mpeg")

    assert observed == [5.0]

    def timed_out_provider(_request, _destination=None):
        raise TimeoutError("provider timed out")

    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_open_provider", side_effect=timed_out_provider
    ), patch(
        "contextual_orchestrator.orchestrator.time.monotonic", side_effect=[10.0, 15.0]
    ), client.request_settings(request_deadline_monotonic=15.0):
        with pytest.raises(RequestDeadlineExceeded):
            client.proxy_send_bytes(agent, "audio/speech", {})


def test_openrouter_image_alias_uses_its_dedicated_images_endpoint() -> None:
    agent = ModelAgent(
        "image_member",
        "provider/image",
        tags=("image",),
        group_name="image_group",
        provider_name="openrouter",
    )
    orchestrator = TaskOrchestrator([agent])
    observed: list[tuple[str, dict]] = []

    def send(_agent: ModelAgent, endpoint: str, payload: dict) -> dict:
        observed.append((endpoint, payload))
        return {"model": payload["model"], "data": []}

    orchestrator.client.proxy_send = send  # type: ignore[method-assign]
    orchestrator.proxy_capability(
        {"model": "image-group", "prompt": "diagram", "routing": {"channel": "sync"}},
        capability="image",
        endpoint="images/generations",
    )

    assert observed == [("images", {"model": "provider/image", "prompt": "diagram"})]


def test_free_virtual_model_uses_only_zero_cost_media_models() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("paid_video", "provider/paid", tags=("video",), priority=100),
        ModelAgent("free_video", "provider/free", tags=("video", "cost:free")),
    ])

    result = orchestrator.proxy_capability(
        {"model": orchestrator.FREE_MODEL, "prompt": "demo"},
        capability="video",
        endpoint="videos",
    )

    assert result["model"] == "provider/free"


def test_free_virtual_model_fails_closed_without_zero_cost_media_models() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("paid_video", "provider/paid", tags=("video",)),
    ])

    with pytest.raises(RuntimeError, match="no enabled zero-cost model"):
        orchestrator.proxy_capability(
            {"model": orchestrator.FREE_MODEL, "prompt": "demo"},
            capability="video",
            endpoint="videos",
        )


def test_ungrouped_capability_routes_record_measured_outcomes() -> None:
    agent = ModelAgent("free_video", "provider/free", tags=("video", "cost:free"))
    orchestrator = TaskOrchestrator([agent])

    orchestrator.proxy_capability(
        {"model": orchestrator.FREE_MODEL, "prompt": "demo"},
        capability="video",
        endpoint="videos",
    )

    assert orchestrator._group_router.member_report(agent.id)["success_count"] == 1


def test_capability_endpoint_reports_unavailable_and_unknown_models() -> None:
    server = build_server(
        TaskOrchestrator([ModelAgent("text_member", "provider/text", tags=("text",))]),
        port=0,
        security=SecurityConfig(auth_token=TOKEN),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        status, body = _post_error(port, "/v1/videos", {"prompt": "demo"})
        assert status == 503 and body["error"]["code"] == "capability_unavailable"
        status, body = _post_error(
            port, "/v1/videos", {"model": "missing-group", "prompt": "demo"}
        )
        assert status == 400 and body["error"]["code"] == "invalid_model"
    finally:
        server.shutdown()
