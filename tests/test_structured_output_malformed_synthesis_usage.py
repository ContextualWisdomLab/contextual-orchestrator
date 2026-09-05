"""False-negative regression for billed malformed structured synthesis attempts."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ProviderResponseError, ProviderUpstreamError


def _response_format() -> dict[str, object]:
    """Return a strict response contract with one accepted value."""
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


def _workflow() -> dict[str, object]:
    """Return bounded pre-synthesis evidence for focused recovery tests."""
    return {
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {},
        "plan_source": "template",
    }


def _usage(completion_tokens: int) -> dict[str, int]:
    """Return canonicalizable billed token evidence."""
    return {
        "prompt_tokens": 2,
        "completion_tokens": completion_tokens,
        "total_tokens": completion_tokens + 2,
    }


def test_malformed_synthesis_usage_survives_virtual_failover() -> None:
    """A billed no-content synthesis remains in trace and spend after recovery."""
    first = ModelAgent("first_agent", "first-model", "mock://first", group_name="test_group")
    second = ModelAgent("second_agent", "second-model", "mock://second", group_name="test_group")
    orchestrator = TaskOrchestrator([first, second])
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == first.id:
            return {
                "choices": [{"message": {}}],
                "usage": _usage(7),
            }
        return {
            "choices": [{"message": {"content": '{"input_count":10}'}}],
            "usage": _usage(3),
        }

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _response_format(),
            },
            single_agent=False,
        )

    assert calls == [first.id, second.id]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    run = orchestrator.get_workflow_run(result["orchestration"]["workflow_run_id"])
    attempts = run["trace"][-2:]
    assert [step["agent_id"] for step in attempts] == [first.id, second.id]
    assert [step["validation_outcome"] for step in attempts] == [
        "provider_error",
        "accepted",
    ]
    assert [step["usage"]["completion_tokens"] for step in attempts] == [7, 3]
    assert orchestrator.budget_status()["spent_output_tokens"] == 10
    assert orchestrator._circuit[first.id]["failures"] == 1
    assert orchestrator._group_router.member_report(first.id)["failure_count"] == 1
    assert orchestrator._group_router.member_report(second.id)["failure_count"] == 0
    assert orchestrator._group_router.member_report(second.id)["success_count"] == 1


@pytest.mark.parametrize("prior_response", [False, True])
def test_response_rejection_before_return_never_reuses_prior_usage(prior_response: bool) -> None:
    """A client rejection before return has no response usage to copy or dereference."""
    first = ModelAgent("first_agent", "first-model", "mock://catalog", group_name="test_group")
    rejected = ModelAgent("rejected_agent", "rejected-model", "mock://catalog", group_name="test_group")
    final = ModelAgent("final_agent", "final-model", "mock://final", group_name="test_group")
    candidates = [first, rejected, final]
    orchestrator = TaskOrchestrator(candidates)
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        calls.append(agent.id)
        if agent.id == first.id:
            if prior_response:
                return {"choices": [{"message": {}}], "usage": _usage(7)}
            raise ProviderUpstreamError(
                agent_id=agent.id, model=agent.model, error_code="api_error",
                message="upstream provider unavailable", client_status=502,
                provider_status=502, retryable=True, transport="structured_synthesis",
            )
        if agent.id == rejected.id:
            raise ProviderResponseError("provider response rejected before return")
        return {"choices": [{"message": {"content": '{"input_count":10}'}}], "usage": _usage(3)}

    with (
        patch.object(orchestrator, "conduct", return_value=_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=candidates),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _response_format(),
            },
            single_agent=False,
        )

    assert calls == [agent.id for agent in candidates]
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    run = orchestrator.get_workflow_run(result["orchestration"]["workflow_run_id"])
    rejected_step = next(step for step in run["trace"] if step["agent_id"] == rejected.id)
    assert rejected_step["validation_outcome"] == "provider_error"
    assert "usage" not in rejected_step
    assert sum(
        step["usage"]["completion_tokens"] for step in run["trace"] if "usage" in step
    ) == (10 if prior_response else 3)
    assert orchestrator.budget_status()["spent_output_tokens"] is None
    for agent in (first, rejected):
        assert orchestrator._circuit[agent.id]["failures"] == 1
        assert orchestrator._group_router.member_report(agent.id)["failure_count"] == 1
    assert orchestrator._group_router.member_report(final.id)["success_count"] == 1
