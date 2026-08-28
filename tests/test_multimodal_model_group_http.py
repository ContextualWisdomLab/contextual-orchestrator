"""Capability endpoints route operator-defined model groups across every modality."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.cost_router import CostRoutingCoordinator
from contextual_orchestrator.orchestrator import ProviderRequestTooLargeError
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.video_jobs import VideoJobContractError

TOKEN = "multimodal_group_token"


def _equivalence(capability: str) -> dict[str, object]:
    return {
        "contract_id": "reviewed_replica_contract",
        "model_revision": "revision_2026_08",
        "reasoning_effort_profile": "not_applicable",
        "capability_set": (capability,),
        "structured_output_contract": "openai_compatible_v1",
        "accuracy_class": "provider_full_precision",
        "data_residency_policy": "kr_region_only",
        "retention_policy": "zero_retention",
        "context_limit": 128_000,
        "pricing_evidence_id": "catalog_snapshot_2026_08_26",
        "hedge_eligible": True,
        "cancellation_supported": False,
        "execution_policy": "immediate_race",
    }


def _post(port: int, path: str, payload: dict, *, token: str = TOKEN) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
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


def _get(port: int, path: str, *, token: str = TOKEN) -> tuple[int, bytes, str]:
    """Issue one authenticated inference GET request."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read(), response.headers.get_content_type()


def _get_error(port: int, path: str, *, token: str = TOKEN) -> tuple[int, dict]:
    """Issue one authenticated GET request and decode its error envelope."""
    try:
        _get(port, path, token=token)
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


def test_video_poll_and_content_use_the_submission_provider() -> None:
    """Async video follow-ups stay bound to the measured submission winner."""
    first = ModelAgent(
        "first_video", "provider/first", tags=("video",), group_name="video_group"
    )
    second = ModelAgent(
        "second_video", "provider/second", tags=("video",), group_name="video_group"
    )
    orchestrator = TaskOrchestrator([first, second])
    orchestrator._group_router.observe_failure(first.id)
    orchestrator._group_router.observe_success(second.id, 0.1)
    followups: list[tuple[str, str]] = []
    orchestrator.client.proxy_send = (  # type: ignore[method-assign]
        lambda agent, _endpoint, payload: {
            "id": "provider-video-123",
            "model": payload["model"],
            "status": "queued",
        }
    )
    orchestrator.client.proxy_get_json = (  # type: ignore[method-assign]
        lambda agent, endpoint, **_kwargs: (
            followups.append((agent.id, endpoint))
            or {
                "id": "provider-video-123",
                "status": "completed",
                "metadata": {
                    "status_url": "https://provider.invalid/videos/provider-video-123"
                },
            }
        )
    )
    orchestrator.client.proxy_get_bytes = (  # type: ignore[method-assign]
        lambda agent, endpoint, **_kwargs: (
            followups.append((agent.id, endpoint)) or (b"video", "video/mp4")
        )
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        status, raw, _ = _post(
            port,
            "/v1/videos",
            {"model": "video-group", "prompt": "product walkthrough"},
        )
        gateway_job_id = json.loads(raw)["id"]
        assert status == 200
        assert gateway_job_id.startswith("videojob_")

        status, raw, content_type = _get(port, f"/v1/videos/{gateway_job_id}")
        assert status == 200 and content_type == "application/json"
        assert json.loads(raw) == {
            "id": gateway_job_id,
            "status": "completed",
            "metadata": {
                "status_url": f"https://provider.invalid/videos/{gateway_job_id}"
            },
        }

        status, raw, content_type = _get(
            port, f"/v1/videos/{gateway_job_id}/content"
        )
        assert status == 200 and content_type == "video/mp4" and raw == b"video"
        assert followups == [
            ("second_video", "videos/provider-video-123"),
            ("second_video", "videos/provider-video-123/content"),
        ]
    finally:
        server.shutdown()


def test_video_followup_rejects_reconfigured_provider_account() -> None:
    """A reused agent id cannot redirect an existing job to another account."""
    agent = ModelAgent(
        "video_owner", "provider/video", tags=("video",), credential_key="ACCOUNT_ONE"
    )
    orchestrator = TaskOrchestrator([agent])
    followups: list[str] = []
    orchestrator.client.proxy_send = (  # type: ignore[method-assign]
        lambda *_args: {"id": "provider-job", "status": "queued"}
    )
    orchestrator.client.proxy_get_json = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: followups.append("called") or {}
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        status, raw, _ = _post(
            port, "/v1/videos", {"model": "provider/video", "prompt": "demo"}
        )
        assert status == 200
        gateway_job_id = json.loads(raw)["id"]
        orchestrator.candidates[0] = ModelAgent(
            "video_owner",
            "provider/video",
            tags=("video",),
            credential_key="ACCOUNT_TWO",
        )

        status, body = _get_error(port, f"/v1/videos/{gateway_job_id}")
        assert status == 503
        assert body["error"]["code"] == "video_provider_unavailable"
        assert followups == []
    finally:
        server.shutdown()


def test_video_submission_does_not_race_uncancellable_async_jobs() -> None:
    """Equivalent endpoints submit one owned async job, never orphan losers."""
    agents = [
        ModelAgent(
            "first_video",
            "provider/shared",
            tags=("video",),
            group_name="video_group",
            endpoint_equivalence=_equivalence("video"),
        ),
        ModelAgent(
            "second_video",
            "provider/shared",
            tags=("video",),
            group_name="video_group",
            endpoint_equivalence=_equivalence("video"),
        ),
    ]
    orchestrator = TaskOrchestrator(agents)
    submissions: list[str] = []
    orchestrator.client.proxy_send = (  # type: ignore[method-assign]
        lambda agent, _endpoint, _payload: (
            submissions.append(agent.id)
            or {"id": f"job-{agent.id}", "status": "queued"}
        )
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, raw, _ = _post(
            server.server_address[1],
            "/v1/videos",
            {"model": "video-group", "prompt": "product walkthrough"},
        )
        assert status == 200
        assert json.loads(raw)["id"].startswith("videojob_")
        assert submissions == ["first_video"]
    finally:
        server.shutdown()


def test_video_job_is_scoped_to_authenticated_principal() -> None:
    agent = ModelAgent("video_owner", "provider/video", tags=("video",))
    orchestrator = TaskOrchestrator([agent])
    orchestrator.client.proxy_send = lambda *_args: {"id": "provider-job", "status": "queued"}  # type: ignore[method-assign]
    orchestrator.client.proxy_get_json = lambda *_args, **_kwargs: {"id": "provider-job", "status": "completed"}  # type: ignore[method-assign]
    security = SecurityConfig(
        bearer_verifier=lambda token, scope: scope == "inference" and token in {"tenant-one", "tenant-two"}
    )
    server = build_server(orchestrator, port=0, security=security)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        _, raw, _ = _post(port, "/v1/videos", {"prompt": "demo"}, token="tenant-one")
        job_id = json.loads(raw)["id"]
        status, body = _get_error(port, f"/v1/videos/{job_id}", token="tenant-two")
        assert status == 404 and body["error"]["code"] == "video_job_not_found"
        assert _get(port, f"/v1/videos/{job_id}", token="tenant-one")[0] == 200
    finally:
        server.shutdown()


def test_video_submission_ledgers_only_concrete_provider_usage() -> None:
    agent = ModelAgent("video_owner", "provider/video", tags=("video",))
    orchestrator = TaskOrchestrator([agent])
    coordinator = CostRoutingCoordinator(orchestrator)
    orchestrator.client.proxy_send = lambda *_args: {  # type: ignore[method-assign]
        "id": "provider-job",
        "status": "completed",
        "usage": {"input_tokens": 7, "output_tokens": 2},
    }
    orchestrator.client.proxy_get_json = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "id": "provider-job",
        "status": "completed",
        "usage": {"input_tokens": 9, "output_tokens": 3},
    }
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=TOKEN),
        coordinator=coordinator,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, raw, _ = _post(
            server.server_address[1], "/v1/videos", {"prompt": "demo"}
        )
        assert status == 200
        assert _get(
            server.server_address[1], f"/v1/videos/{json.loads(raw)['id']}"
        )[0] == 200
        row = coordinator.ledger.records()[0]
        assert (row["prompt_tokens"], row["completion_tokens"]) == (7, 2)
        assert row["measurement_status"] == "measured"
    finally:
        server.shutdown()


def test_untrackable_video_submission_is_not_recorded_as_routing_success() -> None:
    """Ownership registration must succeed before routing records success."""
    agent = ModelAgent("video_owner", "provider/video", tags=("video",))
    orchestrator = TaskOrchestrator([agent])
    orchestrator.client.proxy_send = (  # type: ignore[method-assign]
        lambda _agent, _endpoint, _payload: {"status": "queued"}
    )

    def reject_untrackable(_owner: ModelAgent, _result: object) -> None:
        raise VideoJobContractError("missing provider job id")

    with pytest.raises(VideoJobContractError):
        orchestrator.proxy_capability(
            {"prompt": "product walkthrough"},
            capability="video",
            endpoint="videos",
            selection_sink=reject_untrackable,
        )

    assert orchestrator._group_router.member_report(agent.id)["success_count"] == 0


def test_video_provider_outage_returns_documented_503() -> None:
    """A configured owner that cannot answer remains unavailable, not a 500."""
    agent = ModelAgent("video_owner", "provider/video", tags=("video",))
    orchestrator = TaskOrchestrator([agent])
    orchestrator.client.proxy_send = (  # type: ignore[method-assign]
        lambda _agent, _endpoint, _payload: {"id": "provider-job", "status": "queued"}
    )
    orchestrator.client.proxy_get_json = (  # type: ignore[method-assign]
        lambda _agent, _endpoint, **_kwargs: (_ for _ in ()).throw(ConnectionError("offline"))
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        _, raw, _ = _post(port, "/v1/videos", {"prompt": "demo"})
        gateway_job_id = json.loads(raw)["id"]
        status, body = _get_error(port, f"/v1/videos/{gateway_job_id}")
        assert status == 503
        assert body["error"]["code"] == "video_provider_unavailable"
    finally:
        server.shutdown()


def test_expired_provider_video_job_stops_polling_with_404() -> None:
    """An upstream-gone job tells the client to submit a new request."""
    agent = ModelAgent("video_owner", "provider/video", tags=("video",))
    orchestrator = TaskOrchestrator([agent])
    orchestrator.client.proxy_send = (  # type: ignore[method-assign]
        lambda _agent, _endpoint, _payload: {"id": "provider-job", "status": "queued"}
    )
    orchestrator.client.proxy_get_json = (  # type: ignore[method-assign]
        lambda _agent, endpoint, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError(endpoint, 404, "gone", {}, None)
        )
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        _, raw, _ = _post(port, "/v1/videos", {"prompt": "demo"})
        gateway_job_id = json.loads(raw)["id"]
        status, body = _get_error(port, f"/v1/videos/{gateway_job_id}")
        assert status == 404
        assert body["error"]["code"] == "video_job_not_found"
        assert body["error"]["message"] == (
            "The video job is no longer available; submit a new video request."
        )
    finally:
        server.shutdown()


def test_image_alias_uses_the_provider_endpoint_without_provider_special_case() -> None:
    agent = ModelAgent(
        "image_member",
        "vendor/image",
        tags=("image",),
        group_name="image_group",
        provider_name="vendor",
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

    assert observed == [
        ("images/generations", {"model": "vendor/image", "prompt": "diagram"})
    ]


def test_capability_request_size_exhaustion_preserves_413_without_penalty() -> None:
    """Oversized capability requests do not degrade provider health."""
    agents = [
        ModelAgent("first_image", "provider/image", tags=("image",), group_name="image_group"),
        ModelAgent("second_image", "provider/image", tags=("image",), group_name="image_group"),
    ]
    orchestrator = TaskOrchestrator(agents)

    def reject_size(_agent: ModelAgent, _endpoint: str, _payload: dict) -> dict:
        raise urllib.error.HTTPError("https://provider.invalid/images", 413, "too large", None, None)

    orchestrator.client.proxy_send = reject_size  # type: ignore[method-assign]

    with pytest.raises(ProviderRequestTooLargeError, match="every eligible provider"):
        orchestrator.proxy_capability(
            {"model": "image-group", "prompt": "large image"},
            capability="image",
            endpoint="images/generations",
        )

    assert all(
        orchestrator._group_router.member_report(agent.id)["failure_count"] == 0
        for agent in agents
    )


def test_raced_capability_request_size_exhaustion_preserves_413_without_penalty() -> None:
    """413s in the equivalent-endpoint race do not open provider circuits."""
    agents = [
        ModelAgent(
            "first_image",
            "provider/image",
            tags=("image",),
            group_name="image_group",
            endpoint_equivalence=_equivalence("image"),
        ),
        ModelAgent(
            "second_image",
            "provider/image",
            tags=("image",),
            group_name="image_group",
            endpoint_equivalence=_equivalence("image"),
        ),
    ]
    orchestrator = TaskOrchestrator(agents)

    def reject_size(_agent: ModelAgent, _endpoint: str, _payload: dict) -> dict:
        raise urllib.error.HTTPError("https://provider.invalid/images", 413, "too large", None, None)

    orchestrator.client.proxy_send = reject_size  # type: ignore[method-assign]

    with pytest.raises(ProviderRequestTooLargeError, match="every eligible provider"):
        orchestrator.proxy_capability(
            {"model": "image_group", "prompt": "large image"},
            capability="image",
            endpoint="images/generations",
        )

    assert all(
        orchestrator._group_router.member_report(agent.id)["failure_count"] == 0
        for agent in agents
    )


def test_capability_request_size_exhaustion_returns_http_413() -> None:
    """Capability routes keep oversized upstream requests as client errors."""
    agent = ModelAgent("image_member", "provider/image", tags=("image",), group_name="image_group")
    orchestrator = TaskOrchestrator([agent])

    def reject_size(_agent: ModelAgent, _endpoint: str, _payload: dict) -> dict:
        raise urllib.error.HTTPError("https://provider.invalid/images", 413, "too large", None, None)

    orchestrator.client.proxy_send = reject_size  # type: ignore[method-assign]
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post_error(
            server.server_address[1],
            "/v1/images/generations",
            {"model": "image-group", "prompt": "large image"},
        )
        assert status == 413
        assert body["error"]["code"] == "request_too_large"
    finally:
        server.shutdown()


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


@pytest.mark.parametrize(
    ("capability", "endpoint", "binary"),
    [
        ("image", "images/generations", False),
        ("speech", "audio/speech", True),
        ("transcription", "audio/transcriptions", False),
        ("embedding", "embeddings", False),
        ("rerank", "rerank", False),
        ("audio", "chat/completions", False),
    ],
)
def test_explicit_equivalent_endpoints_race_for_every_capability(
    capability: str, endpoint: str, binary: bool
) -> None:
    agents = [
        ModelAgent(
            "slow_endpoint", "provider/shared", tags=(capability,),
            group_name="shared_model_group", endpoint_equivalence=_equivalence(capability),
        ),
        ModelAgent(
            "fast_endpoint", "provider/shared", tags=(capability,),
            group_name="shared_model_group", endpoint_equivalence=_equivalence(capability),
        ),
    ]
    orchestrator = TaskOrchestrator(agents)

    def result(agent: ModelAgent) -> dict | tuple[bytes, str]:
        if agent.id == "slow_endpoint":
            time.sleep(0.05)
        return (b"media", "audio/mpeg") if binary else {"model": agent.model, "data": []}

    orchestrator.client.proxy_send = lambda agent, _endpoint, _payload: result(agent)  # type: ignore[method-assign]
    orchestrator.client.proxy_send_bytes = lambda agent, _endpoint, _payload: result(agent)  # type: ignore[method-assign]
    value = orchestrator.proxy_capability(
        {"model": "shared-model-group", "prompt": "request"},
        capability=capability,
        endpoint=endpoint,
        binary=binary,
    )
    assert value == ((b"media", "audio/mpeg") if binary else {"model": "provider/shared", "data": []})
    events = orchestrator.list_recent_audit_events()
    race_event = next(event for event in events if event["event_type"] == "equivalent_endpoint_race_completed")
    assert race_event["event_detail"]["winner_endpoint_id"] == "fast_endpoint"
    assert set(race_event["event_detail"]["attempted_endpoint_ids"]) == {
        "slow_endpoint", "fast_endpoint"
    }
    attempt_events = [
        event for event in events
        if event["event_type"] == "equivalent_endpoint_attempt_completed"
    ]
    assert attempt_events
    assert all(
        event["event_detail"]["duplicate_cost_evidence"]
        == "unavailable_requires_provider_invoice"
        for event in attempt_events
    )


def test_fast_empty_media_response_cannot_beat_slower_valid_response() -> None:
    agents = [
        ModelAgent(
            "empty_endpoint", "provider/shared", tags=("image",),
            group_name="shared_image_group", endpoint_equivalence=_equivalence("image"),
        ),
        ModelAgent(
            "valid_endpoint", "provider/shared", tags=("image",),
            group_name="shared_image_group", endpoint_equivalence=_equivalence("image"),
        ),
    ]
    orchestrator = TaskOrchestrator(agents)

    def send(agent: ModelAgent, _endpoint: str, _payload: dict) -> dict:
        if agent.id == "valid_endpoint":
            time.sleep(0.01)
            return {"data": [{"url": "https://example.invalid/image.png"}]}
        return {}

    orchestrator.client.proxy_send = send  # type: ignore[method-assign]
    assert orchestrator.proxy_capability(
        {"model": "shared-image-group", "prompt": "diagram"},
        capability="image",
        endpoint="images/generations",
    ) == {"data": [{"url": "https://example.invalid/image.png"}]}
