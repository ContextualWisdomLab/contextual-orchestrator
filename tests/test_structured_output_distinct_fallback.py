"""Regression contracts for bounded structured-output candidate recovery."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import (
    BudgetExceededError,
    ProviderRequestTooLargeError,
    ProviderResponseError,
    ProviderUpstreamError,
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


def test_virtual_structured_transport_failure_advances_to_next_candidate() -> None:
    """A retryable provider 502 cannot strand a virtual request on one candidate."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
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
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert calls == [first.id, second.id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'


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
    first = ModelAgent("first_agent", "first-model", "mock://catalog")
    second = ModelAgent("second_agent", "second-model", "mock://catalog")
    other = ModelAgent("other_agent", "other-model", "mock://other")
    orchestrator = TaskOrchestrator([first, second, other])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        status = failure_order[len(calls) - 1]
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

    assert calls == [first.id, second.id]
    assert exc_info.value.error_code == "api_error"
    assert exc_info.value.client_status == 502
    assert exc_info.value.provider_status == 502
    assert exc_info.value.retryable is True


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


def test_requested_endpoint_scope_never_crosses_to_another_endpoint() -> None:
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
        return _completion('{"input_count":6}', 1)

    with (
        orchestrator.routing_endpoint_scope(
            "https://first.example/v1",
            TaskOrchestrator.AUTO_MODEL,
        ),
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(ProviderResponseError) as exc_info,
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

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


def test_malformed_synthesis_response_enforces_budget_before_next_candidate() -> None:
    """A billed malformed synthesis that itself exhausts the budget must stop
    there, not silently bill a second provider call before the budget check
    catches up. Otherwise a request can spend past the configured limit."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second], budget_max_output_tokens=2)
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
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
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
        pytest.raises(BudgetExceededError),
    ):
        orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert calls == [first.id]
    assert orchestrator.budget_status()["spent_output_tokens"] == 3
    failed = next(iter(orchestrator._workflow_runs.values()))
    assert failed["failure"]["code"] == "structured_budget_exceeded"


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


def test_initial_same_endpoint_replacement_keeps_cross_endpoint_recovery_pool() -> None:
    """A stale initial candidate can still recover to another endpoint after repair failure."""
    stale = ModelAgent("stale_agent", "stale-model", "mock://catalog")
    live = ModelAgent("live_agent", "live-model", "mock://catalog")
    other = ModelAgent("other_agent", "other-model", "mock://other")
    orchestrator = TaskOrchestrator([stale, live, other])
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
        patch.object(orchestrator, "_ranked_agents", return_value=[stale, live, other]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            _request(TaskOrchestrator.AUTO_MODEL),
            single_agent=False,
        )

    assert calls == [live.id, live.id, other.id]
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

    reloaded = TaskOrchestrator([first], state_db=str(state_db))
    assert reloaded.get_workflow_run(run_id)["failure"]["code"] == "structured_output_exhausted"
    assert reloaded.list_recent_runs() == []
    assert reloaded.count_workflow_runs() == 0
    assert reloaded.budget_status()["spent_output_tokens"] == 2
