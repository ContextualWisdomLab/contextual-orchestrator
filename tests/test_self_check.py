from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing", "planning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation"), priority=1),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review"), priority=2),
        ]
    )


def test_route_once() -> None:
    result = build().complete([{"role": "user", "content": "Write a short status update."}], mode="auto")
    assert result["mode"] == "route"
    assert len(result["trace"]) == 1
    assert result["trace"][0]["role"] == "worker"


def test_conduct_workflow() -> None:
    result = build().complete(
        [{"role": "user", "content": "Analyze the architecture, implement the change, and verify security risks."}],
        mode="auto",
    )
    assert result["mode"] == "conduct"
    assert [step["role"] for step in result["trace"]] == ["thinker", "worker", "verifier", "synthesizer"]
    assert result["trace"][2]["access"] == [0, 1]


if __name__ == "__main__":  # pragma: no cover
    test_route_once()
    test_conduct_workflow()
    print("ok")
