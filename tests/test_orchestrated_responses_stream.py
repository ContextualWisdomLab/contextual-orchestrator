"""Responses-native reasoning summaries for virtual orchestration models."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import threading
import urllib.request
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server


def _post(server: ThreadingHTTPServer, token: str, model: str) -> str:
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/responses",
        data=json.dumps({
            "model": model,
            "input": "Research, implement, and verify a safe design.",
            "reasoning": {"summary": "auto"},
            "stream": True,
        }).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        return response.read().decode()


@pytest.mark.parametrize("model", ["orchestrator/auto", "orchestrator/free"])
def test_virtual_models_stream_openai_reasoning_summaries(model: str) -> None:
    token = "responses_stream_token"
    agents = [
        ModelAgent("paid_worker", "paid-model", tags=("reasoning",), priority=100),
        ModelAgent("free_worker", "free-model", tags=("reasoning", "cost:free")),
    ]
    orchestrator = TaskOrchestrator(agents)
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        stream = _post(server, token, model)
    finally:
        server.shutdown()

    events = [
        json.loads(line[6:])
        for line in stream.splitlines()
        if line.startswith("data: {")
    ]
    types = [event["type"] for event in events]
    assert types[0] == "response.created"
    assert "response.reasoning_summary_text.delta" in types
    assert types[-1] == "response.completed"
    assert [event["sequence_number"] for event in events] == list(range(len(events)))
    summaries = [
        event["delta"]
        for event in events
        if event["type"] == "response.reasoning_summary_text.delta"
    ]
    assert summaries == [
        "Planning the approach.",
        "Executing the selected approach.",
        "Checking the result for errors and unsupported claims.",
        "Preparing the verified final answer.",
    ]
    assert all("[" not in summary for summary in summaries)
    assert any(
        event["event_name"] == "responses_orchestrated"
        and event["event_detail"]["model_name"] == model
        and event["event_detail"]["response_streamed"] is True
        for event in orchestrator._analytics_events
    )
    if model == "orchestrator/free":
        assert {step["agent_id"] for step in orchestrator.conduct(
            [{"role": "user", "content": "Research and verify this."}], model_name=model
        )["trace"]} == {"free_worker"}


def test_free_virtual_model_fails_closed_without_zero_cost_candidate() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("paid_worker", "paid-model")])
    with pytest.raises(RuntimeError, match="no enabled zero-cost model"):
        orchestrator.complete(
            [{"role": "user", "content": "Research and verify this."}],
            model_name="orchestrator/free",
        )


def test_free_ranking_keeps_role_eligibility_ahead_of_measurements() -> None:
    excluded = ModelAgent(
        "excluded_free", "free-fast", tags=("cost:free",), provider_exclusions=("verifier",)
    )
    eligible = ModelAgent("eligible_free", "free-verifier", tags=("cost:free", "verification"))
    orchestrator = TaskOrchestrator([excluded, eligible])
    for _ in range(5):
        orchestrator._group_router.observe_success(excluded.id, 0.001)
    assert orchestrator._select_agent("verify", "verifier", free_only=True) == eligible


def test_free_measurements_survive_unrelated_pool_edits() -> None:
    free = ModelAgent("measured_free", "free-model", tags=("cost:free",))
    paid = ModelAgent("edited_paid", "paid-model")
    orchestrator = TaskOrchestrator([free, paid])
    orchestrator._group_router.observe_success(free.id, 0.1)
    before = orchestrator._group_router.member_report(free.id)
    orchestrator.patch_agent("default", paid.id, {"priority": 2})
    after = orchestrator._group_router.member_report(free.id)
    assert after == before


def test_http_free_virtual_model_returns_400_when_pool_is_empty() -> None:
    token = "responses_stream_token"
    orchestrator = TaskOrchestrator([ModelAgent("paid_worker", "paid-model")])
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/responses",
        data=json.dumps({"model": "orchestrator/free", "input": "hello"}).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
    finally:
        server.shutdown()
    assert raised.value.code == 400
    assert "no enabled zero-cost model" in raised.value.read().decode()


def test_stream_failure_emits_terminal_responses_event() -> None:
    token = "responses_stream_token"
    orchestrator = TaskOrchestrator([
        ModelAgent("free_worker", "free-model", tags=("reasoning", "cost:free"))
    ])
    orchestrator.conduct = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret failure"))  # type: ignore[method-assign]
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        stream = _post(server, token, "orchestrator/free")
    finally:
        server.shutdown()
    assert "event: response.failed" in stream
    assert "secret failure" not in stream
    assert stream.endswith("data: [DONE]\n\n")
    assert "HTTP/1.0 500" not in stream
    event = next(
        event for event in orchestrator._analytics_events
        if event["event_name"] == "responses_orchestrated"
    )
    assert event["event_detail"]["status_code"] == 500
    assert event["event_detail"]["response_status"] == "failed"
