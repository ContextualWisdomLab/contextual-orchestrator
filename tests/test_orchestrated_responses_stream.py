"""Responses-native reasoning summaries for virtual orchestration models."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import threading
import urllib.request

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
