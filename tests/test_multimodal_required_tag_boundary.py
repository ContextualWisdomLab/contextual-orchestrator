"""Regression for enforcing multimodal capability at the invocation boundary."""

from __future__ import annotations

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


class _RecordingClient:
    """Record which synthetic agent the invocation boundary actually calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, _messages, **_kwargs) -> str:
        self.calls.append(agent.id)
        return agent.id


def test_required_tags_filter_an_ineligible_explicit_primary() -> None:
    """A stale or direct caller cannot smuggle a text-only primary into image work."""
    text_agent = ModelAgent(
        "text_agent",
        "text-model",
        tags=("reasoning", "writing"),
        priority=100,
    )
    vision_agent = ModelAgent(
        "vision_agent",
        "vision-model",
        tags=("vision", "reasoning", "writing"),
        priority=1,
    )
    client = _RecordingClient()
    orchestrator = TaskOrchestrator(
        [text_agent, vision_agent],
        client=client,
    )

    answer, served_agent_id, _usage = orchestrator._invoke(
        text_agent,
        [{"role": "user", "content": "Inspect the source image."}],
        text="Inspect the source image.",
        role="worker",
        required_tags=("vision",),
    )

    assert answer == "vision_agent"
    assert served_agent_id == "vision_agent"
    assert client.calls == ["vision_agent"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
