"""Regression tests for current-invocation usage evidence after retries."""

from __future__ import annotations

from typing import Any

import contextual_orchestrator.reasoning_runtime as rr
from contextual_orchestrator.reasoning_control import ReasoningPolicy
from reasoning_fakes import (
    FakeAgent,
    FakeClient,
    FakeOrchestrator,
    common_profile,
)


class _RetryDropsUsageClient(FakeClient):
    """Expose usage for initial calls but not their retry replacements."""

    def __init__(self) -> None:
        super().__init__()
        self.role_calls: dict[str, int] = {}

    def _send(self, agent: FakeAgent, payload: dict[str, Any]) -> str:
        """Return normal outputs while dropping usage on recomputed roles."""
        output = super()._send(agent, payload)
        system = " ".join(
            item.get("content", "")
            for item in payload.get("messages", [])
            if item.get("role") == "system"
        )
        role = next(
            (
                name
                for name in ("worker", "verifier", "synthesizer")
                if f"Role: {name}" in system
            ),
            None,
        )
        if role is not None:
            call_count = self.role_calls.get(role, 0) + 1
            self.role_calls[role] = call_count
            if call_count > 1:
                self._usage = None
        return output


def test_retry_removes_usage_from_replaced_invocations() -> None:
    """Retry rows must not retain usage from provider calls they replaced."""
    agents = [
        FakeAgent("thinker_freshness", "m", ("thinker",)),
        FakeAgent("worker_freshness", "m", ("worker",)),
        FakeAgent("verifier_freshness", "m", ("verifier",)),
        FakeAgent("synth_freshness", "m", ("synthesizer",)),
    ]
    for agent in agents:
        rr.configure_agent_reasoning(agent, common_profile())
    client = _RetryDropsUsageClient()
    orchestrator = FakeOrchestrator(
        agents,
        client=client,
        reasoning_policy=ReasoningPolicy(),
    )

    result = orchestrator.conduct([{"role": "user", "content": "calculate"}])

    assert result["answer"] == "final 42"
    assert client.role_calls == {
        "worker": 2,
        "verifier": 2,
        "synthesizer": 2,
    }
    for role in ("worker", "verifier", "synthesizer"):
        row = next(item for item in result["trace"] if item["role"] == role)
        assert "usage" not in row
        assert row["reasoning"]["reasoning_tokens"] is None
