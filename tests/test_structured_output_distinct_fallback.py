"""Regression contracts for bounded structured-output candidate recovery."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ProviderResponseError


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
        patch.object(
            orchestrator,
            "_failover_candidates",
            return_value=[first, second],
        ),
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
        patch.object(
            orchestrator,
            "_failover_candidates",
            return_value=[first, second],
        ),
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
