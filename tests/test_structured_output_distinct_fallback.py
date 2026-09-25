"""Regression contracts for bounded structured-output candidate recovery."""

from __future__ import annotations

import http.client
import io
import urllib.error
from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import (
    BudgetExceededError,
    ProviderRequestTooLargeError,
    ProviderResponseError,
    ProviderUpstreamError,
)
from contextual_orchestrator.server import _tool_fallback_error_detail
from contextual_orchestrator.tool_fallback import (
    ToolExecutionError,
    ToolFailureKind,
    ToolFallbackStoppedError,
    classify_tool_failure,
)


def _response_format() -> dict[str, object]:
    """Return a strict schema whose only accepted count is ten."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "exact_count",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"input_count": {"const": 10}},
                "required": ["input_count"],
                "additionalProperties": False,
            },
        },
    }


def _completion(content: str, completion_tokens: int) -> dict[str, object]:
    """Build one OpenAI-compatible provider completion with billed usage."""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens + 2,
        },
    }


def _workflow() -> dict[str, object]:
    """Return bounded pre-synthesis evidence for focused recovery tests."""
    return {
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {},
        "plan_source": "template",
    }


def _request(model: str) -> dict[str, object]:
    """Build one virtual structured completion request."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": "classify ten items"}],
        "response_format": _response_format(),
    }


def test_virtual_structured_failure_recovers_on_a_distinct_endpoint_and_keeps_usage() -> None:
    """Invalid synthesis and repair advance once to another eligible endpoint."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == first.id:
            return _completion('{"input_count":6}', len(calls))
        return _completion('{"input_count":10}', 3)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert calls == [first.id, first.id, second.id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    run = orchestrator.get_workflow_run(result["orchestration"]["workflow_run_id"])
    attempts = run["trace"][-3:]
    assert [step["role"] for step in attempts] == [
        "synthesizer",
        "repair",
        "synthesizer",
    ]
    assert [step["validation_outcome"] for step in attempts] == [
        "schema_violation",
        "schema_violation",
        "accepted",
    ]
    assert [step["usage"]["completion_tokens"] for step in attempts] == [1, 2, 3]


@pytest.mark.parametrize("model", [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.FREE_MODEL])
def test_virtual_structured_transport_failure_advances_to_next_candidate(model: str) -> None:
    """A retryable provider 502 cannot strand a virtual request on one candidate."""
    first = ModelAgent("first_agent", "first-model", "mock://first", group_name="test_group", tags=("cost:free",))
    second = ModelAgent("second_agent", "second-model", "mock://second", group_name="test_group", tags=("cost:free",))
    orchestrator = TaskOrchestrator([first, second])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == first.id:
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="upstream_unavailable",
                message="upstream provider unavailable",
                client_status=502,
                provider_status=502,
                retryable=True,
                transport="structured_synthesis",
            )
        return _completion('{"input_count":10}', 1)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            _request(model),
            single_agent=False,
        )

    assert calls == [first.id, second.id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    assert orchestrator._circuit[first.id]["failures"] == 1
    assert orchestrator._group_router.member_report(first.id)["failure_count"] == 1
    assert orchestrator._group_router.member_report(second.id)["failure_count"] == 0
    assert orchestrator._group_router.member_report(second.id)["success_count"] == 1


def test_free_structured_synthesis_waits_out_an_all_429_storm() -> None:
    """Noema's free JSON-schema request recovers after both routes reject it."""
    first = ModelAgent("first_agent", "first-model", "mock://first", group_name="free_pool", tags=("cost:free",))
    second = ModelAgent("second_agent", "second-model", "mock://second", group_name="free_pool", tags=("cost:free",))
    orchestrator = TaskOrchestrator(
        [first, second],
        rate_limit_wait_seconds=1.0,
        rate_limit_unknown_cooldown_seconds=0.01,
    )
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if len(calls) < 3:
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="rate_limit_exceeded",
                message="provider rejected the request",
                client_status=429,
                provider_status=429,
                retryable=True,
                transport="structured_synthesis",
            )
        return _completion('{"input_count":10}', 1)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            _request(TaskOrchestrator.FREE_MODEL),
            single_agent=False,
        )

    assert calls == [first.id, second.id, first.id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    assert [row["provider_status"] for row in result["orchestration"]["route"]["attempted"][:2]] == [429, 429]
    assert result["orchestration"]["route"]["stage"] == "structured_synthesis"
    assert first.id not in orchestrator._circuit
    assert second.id not in orchestrator._circuit


def test_free_structured_synthesis_closes_429_response_before_retry() -> None:
    """An HTTP quota response supplies the cooldown and is closed after classification."""
    agent = ModelAgent("first_agent", "first-model", "mock://first", tags=("cost:free",))
    orchestrator = TaskOrchestrator([agent], rate_limit_wait_seconds=1.0)
    response = io.BytesIO(b"quota exceeded")
    quota_error = urllib.error.HTTPError(
        agent.base_url, 429, "quota exceeded", {"x-ratelimit-reset": "0.01"}, response
    )
    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        patch.object(orchestrator, "_ranked_agents", return_value=[agent]),
        patch.object(
            orchestrator.client,
            "proxy_send_once",
            side_effect=[quota_error, _completion('{"input_count":10}', 1)],
        ) as send,
    ):
        result = orchestrator.proxy_completion(
            _request(TaskOrchestrator.FREE_MODEL), single_agent=False
        )

    assert send.call_count == 2
    assert response.closed
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'


def test_free_structured_synthesis_waits_for_preexisting_cooldown() -> None:
    """A conduct-stage cooldown cannot make final synthesis report a size error."""
    agent = ModelAgent("first_agent", "first-model", "mock://first", tags=("cost:free",))
    orchestrator = TaskOrchestrator([agent], rate_limit_wait_seconds=1.0)
    orchestrator._record_rate_limit(agent.id, 0.01)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        patch.object(orchestrator, "_ranked_agents", return_value=[agent]),
        patch.object(
            orchestrator.client,
            "proxy_send_once",
            return_value=_completion('{"input_count":10}', 1),
        ) as send,
    ):
        result = orchestrator.proxy_completion(
            _request(TaskOrchestrator.FREE_MODEL), single_agent=False
        )

    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    send.assert_called_once()


def test_free_structured_synthesis_preexisting_cooldown_respects_deadline() -> None:
    """A cooled candidate receives no extra call when its wait exceeds the budget."""
    agent = ModelAgent("first_agent", "first-model", "mock://first", tags=("cost:free",))
    orchestrator = TaskOrchestrator([agent], rate_limit_wait_seconds=0.01)
    orchestrator._record_rate_limit(agent.id, 0.2)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        patch.object(orchestrator, "_ranked_agents", return_value=[agent]),
        patch.object(orchestrator.client, "proxy_send_once") as send,
        pytest.raises(ProviderUpstreamError) as caught,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    send.assert_not_called()
    assert caught.value.provider_status == 429
    assert caught.value.extra_detail["route"]["terminal_reason"] == "rate_limited_storm"
    assert caught.value.extra_detail["route"]["eligible_agent_ids"] == [agent.id]
    assert agent.id not in orchestrator._circuit


def test_free_structured_synthesis_exhausted_wait_preserves_429_and_route() -> None:
    """The request deadline stops an all-429 storm without a hidden replay."""
    agents = [
        ModelAgent(f"agent_{index}", f"model-{index}", f"mock://{index}", tags=("cost:free",))
        for index in range(2)
    ]
    orchestrator = TaskOrchestrator(
        agents,
        rate_limit_wait_seconds=0.01,
        rate_limit_unknown_cooldown_seconds=0.2,
    )
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        raise ProviderUpstreamError(
            agent_id=agent.id,
            model=agent.model,
            error_code="rate_limit_exceeded",
            message="provider rejected the request",
            client_status=429,
            provider_status=429,
            retryable=True,
            transport="structured_synthesis",
        )

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agents[0]),
        patch.object(orchestrator, "_ranked_agents", return_value=agents),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ProviderUpstreamError) as caught,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    assert calls == [agent.id for agent in agents]
    assert caught.value.provider_status == 429
    route = caught.value.extra_detail["route"]
    assert route["terminal_reason"] == "rate_limited_storm"
    assert [row["provider_status"] for row in route["attempted"]] == [429, 429]
    assert not orchestrator._circuit


def test_free_structured_synthesis_does_not_replay_a_mixed_failure() -> None:
    """A non-quota failure remains a terminal candidate failure."""
    agents = [
        ModelAgent(f"agent_{index}", f"model-{index}", f"mock://{index}", tags=("cost:free",))
        for index in range(2)
    ]
    orchestrator = TaskOrchestrator(
        agents, rate_limit_wait_seconds=1.0, rate_limit_unknown_cooldown_seconds=0.01
    )
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        status = 429 if agent.id == agents[0].id else 502
        raise ProviderUpstreamError(
            agent_id=agent.id,
            model=agent.model,
            error_code="rate_limit_exceeded" if status == 429 else "upstream_unavailable",
            message="provider rejected the request",
            client_status=status,
            provider_status=status,
            retryable=True,
            transport="structured_synthesis",
        )

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agents[0]),
        patch.object(orchestrator, "_ranked_agents", return_value=agents),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ProviderUpstreamError) as caught,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    assert calls == [agent.id for agent in agents]
    assert caught.value.provider_status == 502
    assert [row["provider_status"] for row in caught.value.extra_detail["route"]["attempted"]] == [429, 502]


def test_unknown_transport_then_two_429s_exposes_structured_stage_without_replay() -> None:
    """A synthetic unknown outcome followed by quota rejects remains fail closed."""
    agents = [
        ModelAgent(f"agent_{index}", f"model-{index}", f"mock://{index}", tags=("cost:free",))
        for index in range(3)
    ]
    orchestrator = TaskOrchestrator(
        agents, rate_limit_wait_seconds=1.0, rate_limit_unknown_cooldown_seconds=0.01
    )
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == agents[0].id:
            raise http.client.RemoteDisconnected("synthetic disconnect")
        raise ProviderUpstreamError(
            agent_id=agent.id,
            model=agent.model,
            error_code="rate_limit_exceeded",
            message="synthetic quota rejection",
            client_status=429,
            provider_status=429,
            retryable=True,
            transport="structured_synthesis",
        )

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agents[0]),
        patch.object(orchestrator, "_ranked_agents", return_value=agents),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ProviderUpstreamError) as caught,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    route = caught.value.extra_detail["route"]
    assert calls == [agent.id for agent in agents]
    assert route["stage"] == "structured_synthesis"
    assert caught.value.detail["route"] == route
    assert [row["provider_status"] for row in route["attempted"]] == [None, 429, 429]
    assert all("synthetic" not in str(row) for row in route["attempted"])


def test_conduct_failure_keeps_its_candidate_route_and_stage() -> None:
    """A structured request identifies conduct failures before final synthesis."""
    agent = ModelAgent("agent_0", "model-0", "mock://0", tags=("cost:free",))
    orchestrator = TaskOrchestrator([agent])
    failure = ProviderUpstreamError(
        agent_id=agent.id,
        model=agent.model,
        error_code="upstream_unavailable",
        message="synthetic disconnect",
        client_status=502,
        retryable=True,
        extra_detail={"route": {
            "eligible_agent_ids": [agent.id],
            "attempted": [{"agent_id": agent.id, "provider_status": None, "outcome": "retryable_transport"}],
            "terminal_reason": "eligible_set_exhausted",
        }},
    )
    with (
        patch.object(orchestrator, "conduct", side_effect=failure),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        pytest.raises(ProviderUpstreamError) as caught,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    assert caught.value.extra_detail["route"]["stage"] == "conduct"
    assert caught.value.extra_detail["route"]["attempted"][0]["agent_id"] == agent.id


def test_conduct_response_failure_keeps_its_route_and_stage() -> None:
    """A malformed conduct response preserves its typed route evidence."""
    agent = ModelAgent("agent_0", "model-0", "mock://0", tags=("cost:free",))
    orchestrator = TaskOrchestrator([agent])
    failure = ProviderResponseError(
        "synthetic invalid response",
        detail={"route": {
            "eligible_agent_ids": [agent.id],
            "attempted": [{"agent_id": agent.id, "outcome": "fail_closed"}],
            "terminal_reason": "fail_closed",
        }},
    )
    with (
        patch.object(orchestrator, "conduct", side_effect=failure),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        pytest.raises(ProviderResponseError) as caught,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    assert caught.value.detail["route"]["stage"] == "conduct"
    assert caught.value.detail["route"]["attempted"][0]["agent_id"] == agent.id


@pytest.mark.parametrize("statuses", [(429, 413), (413, 429)])
def test_free_structured_synthesis_waits_when_other_route_rejects_size(
    statuses: tuple[int, int],
) -> None:
    """A 413 retires only that candidate; the remaining quota route can recover."""
    agents = [
        ModelAgent(f"agent_{index}", f"model-{index}", f"mock://{index}", tags=("cost:free",))
        for index in range(2)
    ]
    orchestrator = TaskOrchestrator(
        agents, rate_limit_wait_seconds=1.0, rate_limit_unknown_cooldown_seconds=0.01
    )
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if len(calls) <= 2:
            status = statuses[len(calls) - 1]
            if status == 413:
                raise ProviderRequestTooLargeError("request exceeds provider limit")
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="rate_limit_exceeded",
                message="provider rejected the request",
                client_status=status,
                provider_status=status,
                retryable=True,
                transport="structured_synthesis",
            )
        return _completion('{"input_count":10}', 1)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agents[0]),
        patch.object(orchestrator, "_ranked_agents", return_value=agents),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    assert calls == [agents[0].id, agents[1].id, agents[statuses.index(429)].id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'


def test_free_structured_repair_recovers_after_all_429() -> None:
    """A quota storm during schema repair waits without replaying initial synthesis."""
    agents = [
        ModelAgent(f"agent_{index}", f"model-{index}", f"mock://{index}", tags=("cost:free",))
        for index in range(2)
    ]
    orchestrator = TaskOrchestrator(
        agents, rate_limit_wait_seconds=1.0, rate_limit_unknown_cooldown_seconds=0.01
    )
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if len(calls) == 1:
            return _completion('{"input_count":6}', 1)
        if len(calls) < 4:
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="rate_limit_exceeded",
                message="provider rejected the request",
                client_status=429,
                provider_status=429,
                retryable=True,
                transport="structured_synthesis",
            )
        return _completion('{"input_count":10}', 1)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agents[0]),
        patch.object(orchestrator, "_ranked_agents", return_value=agents),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    assert calls == [agents[0].id, agents[0].id, agents[1].id, agents[0].id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    assert [row["provider_status"] for row in result["orchestration"]["route"]["attempted"] if row["outcome"] != "served"] == [429, 429]
    assert result["orchestration"]["route"]["stage"] == "structured_repair"


def test_free_structured_synthesis_does_not_replay_nonretryable_429() -> None:
    """The gateway honors a typed nonretryable rejection."""
    agent = ModelAgent("first_agent", "first-model", "mock://first", tags=("cost:free",))
    orchestrator = TaskOrchestrator([agent], rate_limit_wait_seconds=1.0)
    error = ProviderUpstreamError(
        agent_id=agent.id,
        model=agent.model,
        error_code="rate_limit_exceeded",
        message="provider rejected the request",
        client_status=429,
        provider_status=429,
        retryable=False,
        transport="structured_synthesis",
    )
    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        patch.object(orchestrator, "_ranked_agents", return_value=[agent]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=error) as send,
        pytest.raises(ProviderUpstreamError) as caught,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.FREE_MODEL), single_agent=False)

    send.assert_called_once()
    assert caught.value.provider_status == 429
    assert caught.value.error_code == "rate_limit_exceeded"
    assert caught.value.extra_detail["route"]["terminal_reason"] == "fail_closed"


@pytest.mark.parametrize("model", [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.FREE_MODEL])
def test_structured_tool_stop_keeps_prior_candidate_route(model: str) -> None:
    """A later tool stop must keep the earlier structured candidate on the route."""
    first = ModelAgent(
        "first_agent",
        "first-model",
        "mock://first",
        group_name="test_group",
        tags=("cost:free",),
    )
    second = ModelAgent(
        "second_agent",
        "second-model",
        "mock://second",
        group_name="test_group",
        tags=("cost:free",),
    )
    orchestrator = TaskOrchestrator([first, second])

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        if agent.id == first.id:
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="upstream_unavailable",
                message="upstream provider unavailable",
                client_status=502,
                provider_status=502,
                retryable=True,
                transport="structured_synthesis",
            )
        decision = classify_tool_failure(
            ToolExecutionError(
                "request may have completed",
                tool_name="send_message",
                kind=ToolFailureKind.TRANSPORT_ERROR,
                outcome_unknown=True,
            )
        )
        raise ToolFallbackStoppedError(agent.id, decision)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ToolFallbackStoppedError) as excinfo,
    ):
        orchestrator.proxy_completion(_request(model), single_agent=False)

    route = excinfo.value.detail["route"]
    assert [row["outcome"] for row in route["attempted"]] == [
        "retryable_transport",
        "fail_closed",
    ]
    assert route["attempted"][0]["agent_id"] == first.id
    terminal = route["attempted"][1]
    assert terminal["agent_id"] == second.id
    assert terminal["retryable"] is False
    assert "error_code" not in terminal
    assert "provider_status" not in terminal
    assert route["terminal_reason"] == "fail_closed"
    assert route["eligible_agent_ids"] == [first.id, second.id]
    http_detail = _tool_fallback_error_detail(excinfo.value)
    assert http_detail["route"] == route
    assert http_detail["reason_code"]
    assert orchestrator._group_router.member_report(first.id)["failure_count"] == 1
    assert orchestrator._group_router.member_report(second.id)["failure_count"] == 1


@pytest.mark.parametrize("model", [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.FREE_MODEL])
def test_structured_repair_tool_stop_keeps_initial_synthesis_route(model: str) -> None:
    """Repair stops retain transport failure and billed invalid synthesis attempts."""
    first = ModelAgent(
        "first_agent",
        "first-model",
        "mock://first",
        group_name="test_group",
        tags=("cost:free",),
    )
    second = ModelAgent(
        "second_agent",
        "second-model",
        "mock://second",
        group_name="test_group",
        tags=("cost:free",),
    )
    orchestrator = TaskOrchestrator([first, second])

    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if len(calls) == 1:
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="upstream_unavailable",
                message="upstream provider unavailable",
                client_status=502,
                provider_status=502,
                retryable=True,
                transport="structured_synthesis",
            )
        if len(calls) == 2:
            return _completion('{"input_count":6}', 3)
        decision = classify_tool_failure(
            ToolExecutionError(
                "request may have completed",
                tool_name="send_message",
                kind=ToolFailureKind.TRANSPORT_ERROR,
                outcome_unknown=True,
            )
        )
        raise ToolFallbackStoppedError(agent.id, decision)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ToolFallbackStoppedError) as excinfo,
    ):
        orchestrator.proxy_completion(_request(model), single_agent=False)

    assert calls == [first.id, second.id, second.id]
    route = excinfo.value.detail["route"]
    assert [row["outcome"] for row in route["attempted"]] == [
        "retryable_transport",
        "served",
        "fail_closed",
    ]
    assert route["attempted"][0]["agent_id"] == first.id
    terminal = route["attempted"][2]
    assert terminal["agent_id"] == second.id
    assert terminal["retryable"] is False
    assert "error_code" not in terminal
    assert "provider_status" not in terminal
    assert route["terminal_reason"] == "fail_closed"
    assert route["eligible_agent_ids"] == [first.id, second.id]
    http_detail = _tool_fallback_error_detail(excinfo.value)
    assert http_detail["route"] == route
    assert http_detail["reason_code"]
    assert orchestrator._group_router.member_report(first.id)["failure_count"] == 1
    assert orchestrator._group_router.member_report(second.id)["failure_count"] == 1


@pytest.mark.parametrize(
    "failure_order",
    [
        (502, 404),
        (404, 502),
    ],
    ids=["retryable_then_missing", "missing_then_retryable"],
)
def test_virtual_structured_mixed_transport_failures_preserve_retryable_error(
    failure_order: tuple[int, int],
) -> None:
    """A mixed stale/transient endpoint failure remains retryable for callers."""
    first = ModelAgent("first_agent", "first-model", "mock://catalog", group_name="test_group")
    second = ModelAgent("second_agent", "second-model", "mock://catalog", group_name="test_group")
    other = ModelAgent("other_agent", "other-model", "mock://other", group_name="test_group")
    orchestrator = TaskOrchestrator([first, second, other])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        status = (*failure_order, 404)[len(calls) - 1]
        raise ProviderUpstreamError(
            agent_id=agent.id,
            model=agent.model,
            error_code=("api_error" if status == 502 else "model_not_found"),
            message=("upstream provider unavailable" if status == 502 else "model missing"),
            client_status=status,
            provider_status=status,
            retryable=status == 502,
            transport="structured_synthesis",
        )

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second, other]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ProviderUpstreamError) as exc_info,
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert calls == [first.id, second.id, other.id]
    assert exc_info.value.error_code == "api_error"
    assert exc_info.value.client_status == 502
    assert exc_info.value.provider_status == 502
    assert exc_info.value.retryable is True
    for agent in (first, second, other):
        assert orchestrator._circuit[agent.id]["failures"] == 1
        assert orchestrator._group_router.member_report(agent.id)["failure_count"] == 1
        assert orchestrator._group_router.member_report(agent.id)["success_count"] == 0


@pytest.mark.parametrize("model", [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.FREE_MODEL])
@pytest.mark.parametrize("failure_order", [(502, 404, 404), (404, 502, 404), (404, 404, 404)])
def test_virtual_structured_stale_models_do_not_pin_an_unrequested_endpoint(
    model: str, failure_order: tuple[int, int, int],
) -> None:
    """Virtual recovery visits each eligible model, including later-provider siblings."""
    agents = [
        ModelAgent("first_agent", "first-model", "mock://catalog", tags=("cost:free",)),
        ModelAgent("second_agent", "second-model", "mock://catalog", tags=("cost:free",)),
        ModelAgent("third_agent", "third-model", "mock://other", tags=("cost:free",)),
        ModelAgent("fourth_agent", "fourth-model", "mock://other", tags=("cost:free",)),
    ]
    orchestrator = TaskOrchestrator(agents)
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent is agents[-1]:
            return _completion('{"input_count":10}', 1)
        status = failure_order[len(calls) - 1]
        raise ProviderUpstreamError(
            agent_id=agent.id,
            model=agent.model,
            error_code="api_error" if status == 502 else "model_not_found",
            message="synthetic upstream failure",
            client_status=status,
            provider_status=status,
            retryable=status == 502,
            transport="structured_synthesis",
        )

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agents[0]),
        patch.object(orchestrator, "_ranked_agents", return_value=agents),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(_request(model), single_agent=False)

    assert calls == [agent.id for agent in agents]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'


@pytest.mark.parametrize(
    ("failure_order", "final_status", "failure_counts"),
    [
        ((400,), 400, (1, 0)),
        ((502, 400), 400, (1, 1)),
        ((502, 413), 502, (1, 0)),
    ],
    ids=["first_hard_error", "retryable_then_hard_error", "retryable_then_size_limit"],
)
def test_structured_failure_ledgers_attribute_only_failed_candidates(
    failure_order: tuple[int, ...], final_status: int, failure_counts: tuple[int, int],
) -> None:
    """Hard errors count once; a later size limit cannot inherit an earlier failure."""
    first = ModelAgent("first_agent", "first-model", "mock://first", group_name="test_group")
    second = ModelAgent("second_agent", "second-model", "mock://second", group_name="test_group")
    orchestrator = TaskOrchestrator([first, second])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        status = failure_order[len(calls) - 1]
        if status == 413:
            raise ProviderRequestTooLargeError("request exceeds provider limit")
        raise ProviderUpstreamError(
            agent_id=agent.id,
            model=agent.model,
            error_code="api_error" if status == 502 else "invalid_request_error",
            message="upstream request failed",
            client_status=status,
            provider_status=status,
            retryable=status == 502,
            transport="structured_synthesis",
        )

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ProviderUpstreamError) as exc_info,
    ):
        orchestrator.proxy_completion(_request(TaskOrchestrator.AUTO_MODEL), single_agent=False)

    assert calls == [first.id, second.id][:len(failure_order)]
    assert exc_info.value.client_status == final_status
    assert tuple(
        orchestrator._circuit.get(agent.id, {}).get("failures", 0)
        for agent in (first, second)
    ) == failure_counts
    for agent, expected_failures in zip((first, second), failure_counts, strict=True):
        assert orchestrator._group_router.member_report(agent.id)["failure_count"] == expected_failures
        assert orchestrator._group_router.member_report(agent.id)["success_count"] == 0


def test_virtual_structured_exhaustion_is_typed_non_repeating_and_secret_free() -> None:
    """Every candidate receives at most synthesis plus repair before typed exhaustion."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])
    calls: list[str] = []
    sentinel = "provider-output-secret-sentinel"

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        return _completion(f'{{"input_count":6,"note":"{sentinel}"}}', 1)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ProviderResponseError) as exc_info,
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert type(exc_info.value).__name__ == "StructuredOutputExhaustedError"
    assert str(exc_info.value) == (
        "every eligible structured-output candidate violated response_format"
    )
    assert sentinel not in str(exc_info.value)
    assert calls == [first.id, first.id, second.id, second.id]


@pytest.mark.parametrize("missing_model", [False, True])
def test_requested_endpoint_scope_never_crosses_to_another_endpoint(missing_model: bool) -> None:
    """A caller-selected endpoint remains an eligibility boundary during recovery."""
    first = ModelAgent(
        "first_agent",
        "first-model",
        "https://first.example/v1",
    )
    second = ModelAgent(
        "second_agent",
        "second-model",
        "https://second.example/v1",
    )
    orchestrator = TaskOrchestrator([first, second])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if missing_model:
            raise ProviderUpstreamError(
                agent_id=agent.id, model=agent.model, error_code="model_not_found",
                message="model missing", client_status=404, provider_status=404,
                retryable=False, transport="structured_synthesis",
            )
        return _completion('{"input_count":6}', 1)

    with (
        orchestrator.routing_endpoint_scope(
            "https://first.example/v1",
            TaskOrchestrator.AUTO_MODEL,
        ),
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises((ProviderResponseError, ProviderUpstreamError)) as exc_info,
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    if missing_model:
        assert exc_info.value.error_code == "model_not_found"
        assert calls == [first.id]
    else:
        assert type(exc_info.value).__name__ == "StructuredOutputExhaustedError"
        assert calls == [first.id, first.id]
    assert second.id not in calls


def test_structured_budget_rejection_persists_incurred_usage_without_completed_run() -> None:
    """A budget stop after synthesis must charge the call without publishing success KPIs."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    orchestrator = TaskOrchestrator([first], budget_max_output_tokens=1)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_failover_candidates", return_value=[first]),
        patch.object(
            orchestrator.client,
            "proxy_send_once",
            return_value=_completion('{"input_count":6}', 1),
        ),
        pytest.raises(BudgetExceededError),
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert orchestrator.budget_status()["spent_output_tokens"] == 1
    assert len(orchestrator._workflow_runs) == 1
    failed = next(iter(orchestrator._workflow_runs.values()))
    assert failed["failure"]["code"] == "structured_budget_exceeded"
    assert failed["trace"][-1]["validation_outcome"] == "schema_violation"
    assert orchestrator.list_recent_runs() == []
    assert orchestrator.count_workflow_runs() == 0


@pytest.mark.parametrize(
    ("prior_transport_failure", "prior_endpoint"),
    [(False, "mock://first"), (True, "mock://first"), (True, "mock://prior")],
)
def test_malformed_synthesis_response_enforces_budget_before_next_candidate(
    prior_transport_failure: bool, prior_endpoint: str,
) -> None:
    """A billed malformed synthesis that itself exhausts the budget must stop
    there, not silently bill a second provider call before the budget check
    catches up. Otherwise a request can spend past the configured limit."""
    prior = ModelAgent("prior_agent", "prior-model", prior_endpoint, group_name="test_group")
    first = ModelAgent("first_agent", "first-model", "mock://first", group_name="test_group")
    second = ModelAgent("second_agent", "second-model", "mock://second", group_name="test_group")
    candidates = ([prior] if prior_transport_failure else []) + [first, second]
    orchestrator = TaskOrchestrator(candidates, budget_max_output_tokens=2)
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == prior.id:
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="api_error",
                message="upstream provider unavailable",
                client_status=502,
                provider_status=502,
                retryable=True,
                transport="structured_synthesis",
            )
        if agent.id == first.id:
            return {
                "choices": [{"message": {}}],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            }
        return _completion('{"input_count":10}', 1)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=candidates[0]),
        patch.object(orchestrator, "_ranked_agents", return_value=candidates),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(BudgetExceededError),
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert calls == ([prior.id] if prior_transport_failure else []) + [first.id]
    assert orchestrator.budget_status()["spent_output_tokens"] == 3
    failed = next(iter(orchestrator._workflow_runs.values()))
    assert failed["failure"]["code"] == "structured_budget_exceeded"
    assert [
        orchestrator._circuit.get(agent.id, {}).get("failures", 0)
        for agent in candidates
    ] == [int(agent is not second) for agent in candidates]
    for agent in candidates:
        expected_failures = int(agent is not second)
        assert orchestrator._group_router.member_report(agent.id)["failure_count"] == expected_failures


def test_repair_413_retires_candidate_and_restarts_fresh_synthesis() -> None:
    """A too-large repair never migrates its repair prompt to another candidate."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])
    calls: list[tuple[str, dict[str, object]]] = []

    def send(agent: ModelAgent, _endpoint: str, payload: dict[str, object]):
        calls.append((agent.id, payload))
        if len(calls) == 1:
            return _completion('{"input_count":6}', 1)
        if len(calls) == 2:
            raise ProviderRequestTooLargeError(
                "repair request exceeds provider limit",
                agent_id=agent.id,
                model=agent.model,
                transport="structured_repair",
            )
        assert agent.id == second.id
        return _completion('{"input_count":10}', 2)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert [agent_id for agent_id, _payload in calls] == [
        first.id,
        first.id,
        second.id,
    ]
    second_messages = calls[-1][1]["messages"]
    assert isinstance(second_messages, list)
    assert len(second_messages) == 1
    assert second_messages[0]["role"] == "user"
    run = orchestrator.get_workflow_run(result["orchestration"]["workflow_run_id"])
    attempts = run["trace"][-3:]
    assert [step["role"] for step in attempts] == [
        "synthesizer",
        "repair",
        "synthesizer",
    ]
    assert [step["validation_outcome"] for step in attempts] == [
        "schema_violation",
        "request_too_large",
        "accepted",
    ]


@pytest.mark.parametrize("model", [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.FREE_MODEL])
@pytest.mark.parametrize("same_endpoint_available", [False, True])
def test_initial_same_endpoint_replacement_keeps_cross_endpoint_recovery_pool(
    model: str, same_endpoint_available: bool,
) -> None:
    """A stale initial candidate can still recover to another endpoint after repair failure."""
    stale = ModelAgent("stale_agent", "stale-model", "mock://catalog", tags=("cost:free",))
    live = ModelAgent("live_agent", "live-model", "mock://catalog", tags=("cost:free",))
    other = ModelAgent("other_agent", "other-model", "mock://other", tags=("cost:free",))
    candidates = [stale, *([live] if same_endpoint_available else []), other]
    orchestrator = TaskOrchestrator(candidates)
    calls: list[str] = []

    def conduct(*_args, **kwargs):
        kwargs["_excluded_agent_ids"].add(stale.id)
        return _workflow()

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == live.id:
            return _completion('{"input_count":6}', len(calls))
        return _completion('{"input_count":10}', 3)

    with (
        patch.object(orchestrator, "conduct", side_effect=conduct),
        patch.object(orchestrator, "_select_agent", return_value=stale),
        patch.object(orchestrator, "_ranked_agents", return_value=candidates),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            _request(model),
            single_agent=False,
        )

    assert calls == ([live.id, live.id] if same_endpoint_available else []) + [other.id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'


def test_request_too_large_candidate_is_retired_after_transport_failover() -> None:
    """A synthesis-side 413 is never retried after another candidate is attempted."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    third = ModelAgent("third_agent", "third-model", "mock://third")
    orchestrator = TaskOrchestrator([first, second, third])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == first.id:
            raise ProviderRequestTooLargeError(
                "request exceeds provider limit",
                agent_id=agent.id,
                model=agent.model,
                transport="structured_synthesis",
            )
        if agent.id == second.id:
            return _completion('{"input_count":6}', len(calls))
        return _completion('{"input_count":10}', 4)

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second, third]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert calls == [first.id, second.id, second.id, third.id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'


def test_empty_repair_response_persists_billed_usage_before_failure() -> None:
    """A repair response with usage but no content still reaches durable failure evidence."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    orchestrator = TaskOrchestrator([first])

    responses = iter([
        _completion('{"input_count":6}', 1),
        {"choices": [{"message": {}}], "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 2,
            "total_tokens": 4,
        }},
    ])

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first]),
        patch.object(
            orchestrator.client,
            "proxy_send_once",
            side_effect=lambda *_args, **_kwargs: next(responses),
        ),
        pytest.raises(
            ProviderResponseError,
            match="response did not contain assistant content",
        ),
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert orchestrator.budget_status()["spent_output_tokens"] == 3
    failed = next(iter(orchestrator._workflow_runs.values()))
    assert failed["failure"]["code"] == "structured_repair_failed"
    assert [step["validation_outcome"] for step in failed["trace"][-2:]] == [
        "schema_violation",
        "provider_error",
    ]
    assert failed["trace"][-1]["usage"]["completion_tokens"] == 2


def test_failed_structured_run_stays_queryable_but_out_of_recent_completed_metrics(tmp_path) -> None:
    """Failure evidence survives restart without inflating normal completed-run surfaces."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    state_db = tmp_path / "structured-failure.sqlite3"
    orchestrator = TaskOrchestrator([first], state_db=str(state_db))
    try:
        with (
            patch.object(orchestrator, "conduct", return_value=_workflow()),
            patch.object(orchestrator, "_select_agent", return_value=first),
            patch.object(orchestrator, "_failover_candidates", return_value=[first]),
            patch.object(
                orchestrator.client,
                "proxy_send_once",
                return_value=_completion('{"input_count":6}', 1),
            ),
            pytest.raises(ProviderResponseError) as exc_info,
        ):
            orchestrator.proxy_completion(
                _request(TaskOrchestrator.AUTO_MODEL),
                single_agent=False,
            )

        run_id = getattr(exc_info.value, "workflow_run_id", None)
        assert isinstance(run_id, str)
        assert orchestrator.get_workflow_run(run_id)["failure"]["code"] == "structured_output_exhausted"
        assert orchestrator.list_recent_runs() == []
        assert orchestrator.count_workflow_runs() == 0
    finally:
        orchestrator.close()

    reloaded = TaskOrchestrator([first], state_db=str(state_db))
    try:
        assert reloaded.get_workflow_run(run_id)["failure"]["code"] == "structured_output_exhausted"
        assert reloaded.list_recent_runs() == []
        assert reloaded.count_workflow_runs() == 0
        assert reloaded.budget_status()["spent_output_tokens"] == 2
    finally:
        reloaded.close()
