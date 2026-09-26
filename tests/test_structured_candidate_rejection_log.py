"""The gateway logs why a structured-output candidate was rejected.

Noema run 36166447802 (.github) showed four NVIDIA candidates ending in
``circuit_failure`` with no ``provider_attempt_failed`` line: HTTP succeeded,
the strict structured output was rejected twice (synthesis, then repair), and
nothing recorded why. These tests pin a bounded reason on that path.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import _log_structured_candidate_rejected

LOGGER = "contextual_orchestrator.orchestrator"


def _request() -> dict[str, object]:
    """Build one virtual request with a strict schema that only accepts ten."""
    return {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "classify ten items"}],
        "response_format": {
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
        },
    }


def _completion(content: str) -> dict[str, object]:
    """Build one OpenAI-compatible completion."""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }


def test_repair_rejection_logs_bounded_reason_without_content(caplog) -> None:
    """A twice-invalid candidate logs stage=repair with its validation code only."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, object]):
        if agent.id == first.id:
            return _completion('{"input_count":6,"note":"secret-canary"}')
        return _completion('{"input_count":10}')

    workflow = {"mode": "conduct", "answer": "e", "trace": [], "verification": {}, "plan_source": "template"}
    with (
        caplog.at_level(logging.DEBUG, logger=LOGGER),
        patch.object(orchestrator, "conduct", return_value=workflow),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        orchestrator.proxy_completion(_request(), single_agent=False)

    rejected = [r.getMessage() for r in caplog.records if r.getMessage().startswith("structured_candidate_rejected")]
    assert rejected == [
        "structured_candidate_rejected agent_id=first_agent model=first-model stage=repair reason=schema_violation request_id=-"
    ]
    assert "secret-canary" not in caplog.text


def test_unbounded_reason_is_replaced_and_debug_off_is_silent(caplog) -> None:
    """Free text never reaches the log, and nothing is emitted above DEBUG."""
    agent = ModelAgent("a_agent", "a-model", "mock://a")
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        _log_structured_candidate_rejected(agent, "synthesis", "Provider said: key=abc")
    assert "reason=unclassified" in caplog.text
    assert "key=abc" not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _log_structured_candidate_rejected(agent, "synthesis", "provider_error")
    assert caplog.text == ""
