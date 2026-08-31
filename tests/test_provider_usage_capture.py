"""Provider-reported usage capture and explicit unavailable fallbacks.

A gateway that already sees provider `usage` should bill on it, not a char heuristic.
These assert reported completion_tokens flow into spend_analytics and are labeled,
while the mock path stays unavailable.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


class _ReportingClient(ModelClient):
    """Mock-style client that also reports provider usage on each call."""

    def __init__(self, completion_tokens: int) -> None:
        super().__init__()
        self._completion_tokens = completion_tokens

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self._local.usage = {
            "prompt_tokens": 5,
            "completion_tokens": self._completion_tokens,
            "total_tokens": 5 + self._completion_tokens,
        }
        return f"[{agent.id}] answer"


def test_take_usage_returns_and_clears() -> None:
    client = ModelClient()
    client._local.usage = {"completion_tokens": 7}
    assert client.take_usage() == {"completion_tokens": 7}
    assert client.take_usage() is None  # cleared after read


def test_reported_usage_preferred_and_labeled() -> None:
    client = _ReportingClient(completion_tokens=50)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))],
        client=client,
        price_per_million={"priced-model": 10.0},
    )
    # Accounting contract, not dispatch: pin the single-step route path.
    orchestrator._triage_fn = lambda text: False
    orchestrator.run([{"role": "user", "content": "do the work"}])
    row = next(r for r in orchestrator.spend_analytics()["by_model"] if r["model"] == "priced-model")

    assert row["usage_source"] == "reported"
    assert row["output_tokens"] == 50
    assert row["cost_usd"] == round(50 / 1_000_000 * 10.0, 6)


def test_reported_prompt_tokens_surface_in_totals() -> None:
    client = _ReportingClient(completion_tokens=30)  # also reports prompt_tokens=5 per call
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "priced-model", tags=("reasoning",))], client=client)
    orchestrator._triage_fn = lambda text: False  # single-step route accounting
    orchestrator.run([{"role": "user", "content": "route once"}])
    totals = orchestrator.spend_analytics()["totals"]
    assert totals["prompt_tokens_source"] == "reported"
    assert totals["prompt_tokens"] == 5


def test_mock_prompt_tokens_source_is_unavailable() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "free-model", tags=("reasoning",))])
    orchestrator.run([{"role": "user", "content": "no usage here"}])
    totals = orchestrator.spend_analytics()["totals"]
    assert totals["prompt_tokens_source"] == "unavailable"
    assert totals["prompt_tokens"] is None


def test_mock_path_stays_unavailable() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "free-model", tags=("reasoning",))])
    orchestrator.run([{"role": "user", "content": "do the work"}])
    row = next(r for r in orchestrator.spend_analytics()["by_model"] if r["model"] == "free-model")

    assert row["usage_source"] == "unavailable"
    assert row["output_tokens"] is None


def test_conduct_all_steps_reported() -> None:
    client = _ReportingClient(completion_tokens=12)
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "priced-model", tags=("reasoning",))], client=client)
    orchestrator.run([{"role": "user", "content": "big task"}], mode="conduct")
    row = next(r for r in orchestrator.spend_analytics()["by_model"] if r["model"] == "priced-model")
    assert row["usage_source"] == "reported"
    assert row["step_count"] == 4  # thinker/worker/verifier/synthesizer
    assert row["output_tokens"] == 48  # 4 steps x 12 reported tokens


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
