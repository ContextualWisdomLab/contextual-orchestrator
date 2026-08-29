"""Responses-native reasoning summaries for virtual orchestration models."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import threading
import urllib.request
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.cost_router import CostRoutingCoordinator
from contextual_orchestrator.server import (
    RequestError,
    SecurityConfig,
    _require_pool_model,
    build_server,
)


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
        "Preparing the final answer.",
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


def test_conduct_preserves_responses_instructions_for_every_stage() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("workflow_agent", "mock-model", base_url="mock://provider"),
    ])
    original_chat = orchestrator.client.chat
    observed_system_messages: list[str] = []

    def recording_chat(agent: ModelAgent, messages: list[dict], *args, **kwargs) -> str:
        observed_system_messages.append(messages[0]["content"])
        return original_chat(agent, messages, *args, **kwargs)

    orchestrator.client.chat = recording_chat  # type: ignore[method-assign]
    orchestrator.complete(
        [
            {"role": "system", "content": "Answer in Korean."},
            {"role": "user", "content": "Research, implement, and verify the design."},
        ],
        mode="conduct",
    )

    assert observed_system_messages
    assert all("Caller instructions:\nAnswer in Korean." in message for message in observed_system_messages)


def test_conduct_keeps_planned_agent_when_no_vision_alternative_exists() -> None:
    """A multimodal workflow may use its planned model when no tagged alternative exists."""
    orchestrator = TaskOrchestrator([
        ModelAgent("workflow_agent", "mock-model", base_url="mock://provider"),
    ])

    result = orchestrator.conduct([
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ],
        }
    ])

    assert result["trace"]
    assert {step["agent_id"] for step in result["trace"]} == {"workflow_agent"}


def test_duplicate_workflow_roles_close_each_reasoning_summary_part() -> None:
    token = "duplicate_role_stream_token"
    orchestrator = TaskOrchestrator([
        ModelAgent("workflow_agent", "mock-model", base_url="mock://provider"),
    ])
    orchestrator.would_route = lambda *_args, **_kwargs: False  # type: ignore[method-assign]

    def conduct(_messages, *, model_name, progress):
        progress("worker", "started")
        progress("worker", "started")
        progress("worker", "completed")
        progress("worker", "completed")
        return {"answer": "done"}

    orchestrator.conduct = conduct  # type: ignore[method-assign]
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        events = [
            json.loads(line[6:])
            for line in _post(server, token, "orchestrator/auto").splitlines()
            if line.startswith("data: {")
        ]
    finally:
        server.shutdown()

    assert [
        event["summary_index"]
        for event in events
        if event["type"] == "response.reasoning_summary_part.done"
    ] == [0, 1]


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


def test_zero_price_override_is_agent_specific_when_model_ids_are_shared() -> None:
    first = ModelAgent("first_provider", "shared-model")
    second = ModelAgent("second_provider", "shared-model")
    orchestrator = TaskOrchestrator(
        [first, second], price_per_million={"shared-model": 0, first.id: 0}
    )

    assert orchestrator._is_free_agent(first)
    assert not orchestrator._is_free_agent(second)


def test_virtual_capability_models_resolve_to_eligible_upstreams() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("paid_embedding", "paid-embedding", tags=("embedding",), priority=10),
        ModelAgent("free_embedding", "free-embedding", tags=("embedding", "cost:free")),
        ModelAgent("free_text", "free-text", tags=("text", "cost:free")),
    ])
    assert _require_pool_model(
        orchestrator, "orchestrator/auto", required_capability="embedding"
    ) == "paid-embedding"
    assert _require_pool_model(
        orchestrator, "orchestrator/free", required_capability="embedding"
    ) == "free-embedding"
    with pytest.raises(RequestError, match="no enabled video model"):
        _require_pool_model(
            orchestrator, "orchestrator/free", required_capability="video"
        )


def test_virtual_capability_auto_rejects_non_zdr_pool() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("paid_embedding", "paid-embedding", tags=("embedding",))]
    )

    with orchestrator.request_policy(True), pytest.raises(
        RequestError, match="no enabled embedding model"
    ) as raised:
        _require_pool_model(
            orchestrator, TaskOrchestrator.AUTO_MODEL, required_capability="embedding"
        )

    assert raised.value.status == 400


def test_virtual_text_models_require_an_enabled_eligible_pool() -> None:
    """AUTO and FREE fail as client errors before an empty pool reaches routing."""
    empty = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")])
    empty.agents = []
    paid_only = TaskOrchestrator([ModelAgent("paid_worker", "paid-model")])

    with pytest.raises(RequestError, match="no enabled model") as auto_error:
        _require_pool_model(empty, TaskOrchestrator.AUTO_MODEL)
    assert auto_error.value.status == 400
    with pytest.raises(RequestError, match="no enabled zero-cost model") as free_error:
        _require_pool_model(paid_only, TaskOrchestrator.FREE_MODEL)
    assert free_error.value.status == 400


def test_virtual_and_group_models_exclude_disabled_members() -> None:
    """Disabled agents are configuration records, never routable pool capacity."""
    orchestrator = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")])
    disabled = ModelAgent(
        "disabled_agent", "disabled-model", disabled=True, group_name="disabled_group"
    )
    orchestrator.agents = [disabled]

    with pytest.raises(RequestError, match="no enabled model"):
        _require_pool_model(orchestrator, TaskOrchestrator.AUTO_MODEL)
    with pytest.raises(RequestError, match="not available in the agent pool"):
        _require_pool_model(orchestrator, "disabled-group")


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


def test_http_zdr_only_request_filters_the_runtime_candidate_pool() -> None:
    """The request bool, not a provider-specific model list, controls selection."""
    token = "zdr_request_token"
    paid = ModelAgent("paid_worker", "paid-model", group_name="shared_model")
    private = ModelAgent(
        "zdr_worker",
        "zdr-model",
        tags=("privacy:zdr",),
        group_name="shared_model",
    )
    orchestrator = TaskOrchestrator([paid, private])
    coordinator = CostRoutingCoordinator(orchestrator)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=token),
        coordinator=coordinator,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/responses",
        data=json.dumps({
            "model": "orchestrator/auto",
            "input": "hello",
            "zdr_only": True,
        }).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
    finally:
        server.shutdown()

    workflow = orchestrator.get_workflow_run(next(iter(orchestrator._run_order)))
    assert {step["agent_id"] for step in workflow["trace"]} == {private.id}
    assert coordinator.ledger.store.query()


def test_http_virtual_responses_preserves_message_array_and_sampling_controls() -> None:
    token = "responses_array_controls_token"
    orchestrator = TaskOrchestrator([
        ModelAgent("free_worker", "free-model", tags=("reasoning", "cost:free"))
    ])
    observed_messages: list[list[dict]] = []
    observed_settings: list[dict] = []
    original_chat = orchestrator.client.chat

    def recording_chat(agent, messages, *args, **kwargs):
        observed_messages.append(messages)
        observed_settings.append(orchestrator.client.request_settings_snapshot())
        return original_chat(agent, messages, *args, **kwargs)

    orchestrator.client.chat = recording_chat  # type: ignore[method-assign]
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/responses",
        data=json.dumps(
            {
                "model": "orchestrator/free",
                "input": [
                    {"type": "message", "role": "system", "content": "context"},
                    {"type": "message", "role": "user", "content": "question"},
                    {"type": "message", "role": "assistant", "content": "history"},
                ],
                "temperature": 0.73,
                "top_p": 0.81,
                "presence_penalty": 0.2,
                "frequency_penalty": -0.3,
                "max_output_tokens": 33,
            }
        ).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert observed_messages
    assert any(
        [message.get("role") for message in messages][1:4]
        == ["system", "user", "assistant"]
        for messages in observed_messages
    )
    assert observed_settings
    assert all(
        settings["temperature"] == 0.73
        and settings["top_p"] == 0.81
        and settings["presence_penalty"] == 0.2
        and settings["frequency_penalty"] == -0.3
        and settings["max_output_tokens"] == 33
        for settings in observed_settings
    )


@pytest.mark.parametrize(
    "structured_output",
    [
        {"response_format": {"type": "json_object"}},
        {"text": {"format": {"type": "json_schema", "name": "result", "schema": {}}}},
    ],
)
def test_nonstream_orchestrated_responses_support_structured_output(
    structured_output: dict,
) -> None:
    token = "responses_stream_token"
    orchestrator = TaskOrchestrator([
        ModelAgent("free_worker", "free-model", tags=("cost:free", "response_format"))
    ])
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/responses",
        data=json.dumps({"model": "orchestrator/free", "input": "hello", **structured_output}).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = json.loads(response.read())
    finally:
        server.shutdown()
    assert status == 200
    assert body["orchestration"]["mode"] == "conduct"


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
    assert event["event_detail"]["transport_status_code"] == 200
    assert event["event_detail"]["response_status"] == "failed"
