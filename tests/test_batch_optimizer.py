"""Batch-powered optimizer — route-mode evaluations ride the ~50% Batch lane.

batch_route routes many prompts through the provider Batch API and persists them as
normal route runs (usage kept), so spend/observability are unchanged. optimize/evolve
gain use_batch: route configs evaluate via one batch, conduct stays serial.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient, optimize_orchestration  # noqa: E402


class _CountingClient(ModelClient):
    """Counts chat vs batch calls; batch reports usage so spend sees reported tokens."""

    def __init__(self) -> None:
        super().__init__()
        self.chat_calls = 0
        self.batch_calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.chat_calls += 1
        return super().chat(agent, messages, temperature)

    def batch_chat(self, agent: ModelAgent, requests: dict, temperature: float = 0.2,  # type: ignore[override]
                   poll_interval: float = 5.0, poll_timeout: float = 3600.0) -> dict:
        self.batch_calls += 1
        return {
            custom_id: {"content": self._mock(agent, messages),
                        "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}}
            for custom_id, messages in requests.items()
        }


def _orch(client: ModelClient | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing"))],
        client=client,
        price_per_million={"model-x": 10.0},
    )


TASKS = [{"prompt": "task one"}, {"prompt": "task two"}, {"prompt": "task three"}]


def test_batch_route_persists_runs_with_usage() -> None:
    client = _CountingClient()
    orchestrator = _orch(client)
    records = orchestrator.batch_route([t["prompt"] for t in TASKS])

    assert len(records) == 3
    assert client.batch_calls == 1 and client.chat_calls == 0  # one batch, zero serial calls
    assert len(orchestrator._workflow_runs) == 3  # persisted as normal route runs
    spend = orchestrator.spend_analytics()
    assert spend["totals"]["run_count"] == 3
    row = spend["by_model"][0]
    assert row["usage_source"] == "reported"  # batch usage threaded into spend
    assert row["output_tokens"] == 18  # 3 x 6 reported completion tokens


def test_optimizer_use_batch_routes_via_batch_and_matches_serial() -> None:
    batch_client = _CountingClient()
    serial_client = _CountingClient()
    report_batch = optimize_orchestration(
        [{"name": "route_cfg", "orchestrator": _orch(batch_client), "mode": "route"}],
        TASKS, lambda task, answer: 1.0 if "general_agent" in answer else 0.0, use_batch=True)
    report_serial = optimize_orchestration(
        [{"name": "route_cfg", "orchestrator": _orch(serial_client), "mode": "route"}],
        TASKS, lambda task, answer: 1.0 if "general_agent" in answer else 0.0, use_batch=False)

    assert batch_client.batch_calls == 1 and batch_client.chat_calls == 0
    assert serial_client.batch_calls == 0 and serial_client.chat_calls == 3
    # Same mock answers -> identical quality either lane.
    assert report_batch["results"][0]["quality"] == report_serial["results"][0]["quality"] == 1.0


def test_conduct_config_stays_serial_even_with_use_batch() -> None:
    client = _CountingClient()
    optimize_orchestration(
        [{"name": "conduct_cfg", "orchestrator": _orch(client), "mode": "conduct"}],
        TASKS[:1], lambda task, answer: 1.0, use_batch=True)
    assert client.batch_calls == 0  # multi-step cannot batch
    assert client.chat_calls == 4  # thinker/worker/verifier/synthesizer


def test_mock_default_batch_route_works_without_usage() -> None:
    orchestrator = _orch()  # plain ModelClient: mock batch_chat is sync, usage None
    records = orchestrator.batch_route(["hello there"])
    assert records[0]["answer"].startswith("[general_agent:")
    assert orchestrator.spend_analytics()["by_model"][0]["usage_source"] == "estimated"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
