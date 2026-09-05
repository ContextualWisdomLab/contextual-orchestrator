"""False-negative regression for billed malformed structured synthesis attempts."""

from __future__ import annotations

from unittest.mock import patch

from contextual_orchestrator import ModelAgent, TaskOrchestrator


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
