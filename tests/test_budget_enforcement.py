"""Budget enforcement — operator spend cap that refuses runs once exhausted.

Enterprise gateways gate spend. This maintains a constant-time meter with exact
parity to spend analytics, refuses new runs when over the cap, surfaces the state,
and maps to a 429 over HTTP. Default (no cap) is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import BudgetExceededError  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402
from contextual_orchestrator.token_counting import UnavailableTokenCounter  # noqa: E402


def _agent() -> ModelAgent:
    return ModelAgent("general_agent", "test-model", tags=("reasoning",))


class _ExactCounter:
    """Exact synthetic raw-output counter for budget tests."""

    def count_text(self, text: str, model: str) -> int:
        return len(text.encode("utf-8"))


def _orchestrator(agents: list[ModelAgent], **kwargs) -> TaskOrchestrator:
    return TaskOrchestrator(agents, token_counter=_ExactCounter(), **kwargs)


def test_default_no_budget_is_unchanged() -> None:
    orchestrator = _orchestrator([_agent()])
    orchestrator.run([{"role": "user", "content": "one"}])
    orchestrator.run([{"role": "user", "content": "two"}])  # no cap, both allowed
    assert orchestrator.spend_analytics()["budget"]["enabled"] is False


def test_token_budget_allows_then_blocks() -> None:
    orchestrator = _orchestrator([_agent()], budget_max_output_tokens=1)
    orchestrator.run([{"role": "user", "content": "first run is allowed"}])  # spent was 0 at entry

    raised = False
    try:
        orchestrator.run([{"role": "user", "content": "second run is blocked"}])
    except BudgetExceededError as exc:
        raised = True
        assert exc.detail["exceeded"] is True
        assert exc.detail["max_output_tokens"] == 1
    assert raised


def test_enabled_budget_fails_closed_after_unavailable_usage() -> None:
    orchestrator = TaskOrchestrator(
        [_agent()],
        token_counter=UnavailableTokenCounter(),
        budget_max_output_tokens=100,
    )
    orchestrator.run([{"role": "user", "content": "first call has unavailable usage"}])
    budget = orchestrator.budget_status()
    assert budget["measurement_status"] == "unavailable"
    assert budget["enforcement_status"] == "blocked_unavailable"
    assert budget["spent_output_tokens"] is None
    with pytest.raises(BudgetExceededError, match="measurement unavailable"):
        orchestrator.run([{"role": "user", "content": "must not dispatch"}])


def test_cost_budget_fails_closed_for_an_unpriced_served_model() -> None:
    orchestrator = _orchestrator(
        [_agent()],
        budget_max_cost_usd=10.0,
    )
    # With no price book, a cost budget cannot safely admit even the first call.
    budget = orchestrator.budget_status()
    assert budget["enforcement_status"] == "blocked_unavailable"
    with pytest.raises(BudgetExceededError, match="measurement unavailable"):
        orchestrator.run([{"role": "user", "content": "must not dispatch"}])


def test_cost_budget_ignores_unpriced_embedding_only_candidate() -> None:
    orchestrator = _orchestrator(
        [
            ModelAgent("chat_agent", "priced-chat", tags=("capability:chat",)),
            ModelAgent(
                "embedding_agent",
                "unpriced-embedding",
                tags=("capability:embedding",),
            ),
        ],
        price_per_million={"priced-chat": 1.0},
        budget_max_cost_usd=10.0,
    )

    orchestrator.run([{"role": "user", "content": "priced chat workflow"}])

    assert orchestrator.budget_status()["enforcement_status"] == "within_budget"
    assert orchestrator.budget_status()["spent_cost_usd"] > 0
    assert orchestrator.spend_analytics()["budget"] == orchestrator.budget_status()


def test_budget_block_reports_spent_and_remaining() -> None:
    orchestrator = _orchestrator([_agent()], budget_max_output_tokens=1000)
    orchestrator.run([{"role": "user", "content": "measure the budget"}])
    budget = orchestrator.spend_analytics()["budget"]

    assert budget["enabled"] is True
    assert budget["max_output_tokens"] == 1000
    assert budget["spent_output_tokens"] > 0
    assert budget["remaining_output_tokens"] == 1000 - budget["spent_output_tokens"]
    assert budget["exceeded"] is False


def test_cost_budget_blocks() -> None:
    orchestrator = _orchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))],
        price_per_million={"priced-model": 1_000_000.0},  # $1 per token, so any run exceeds a tiny cap
        budget_max_cost_usd=0.001,
    )
    orchestrator.run([{"role": "user", "content": "spend some money"}])  # allowed (cost was 0 at entry)
    assert orchestrator.spend_analytics()["budget"]["exceeded"] is True

    raised = False
    try:
        orchestrator.run([{"role": "user", "content": "now blocked"}])
    except BudgetExceededError:
        raised = True
    assert raised


def test_budget_meter_matches_randomized_recorded_run_analytics() -> None:
    """Incremental token/cost state equals the authoritative full aggregation."""
    agents = [ModelAgent("agent_one", "model-one"), ModelAgent("agent_two", "model-two")]
    orchestrator = _orchestrator(
        agents,
        price_per_million={"model-one": 0.75, "model-two": 3.25},
        budget_max_output_tokens=10_000,
        budget_max_cost_usd=10.0,
    )
    rng = random.Random(846)
    for index in range(100):
        steps = []
        for step_index in range(rng.randint(1, 4)):
            agent = rng.choice(agents)
            output = "x" * rng.randint(0, 80)
            step = {"agent_id": agent.id, "output": output}
            if rng.choice((True, False)):
                step["usage"] = {"completion_tokens": rng.randint(0, 50)}
            steps.append(step)
        orchestrator._replace_workflow_run(
            {
                "workflow_run_id": f"run_{index % 31}",
                "prompt_text": "p" * rng.randint(0, 30),
                "trace": steps,
            }
        )
        assert orchestrator.budget_status() == orchestrator.spend_analytics()["budget"]


def test_budget_status_does_not_scan_recorded_runs() -> None:
    """The per-request gate remains independent of workflow-run cardinality."""
    orchestrator = _orchestrator([_agent()], budget_max_output_tokens=1)
    orchestrator.run([{"role": "user", "content": "record one run"}])
    orchestrator.spend_analytics = lambda: (_ for _ in ()).throw(
        AssertionError("budget_status scanned workflow runs")
    )  # type: ignore[method-assign]
    assert orchestrator.budget_status()["spent_output_tokens"] > 0


def test_budget_meter_rebuilds_from_persisted_runs(tmp_path: Path) -> None:
    """Restarted gates recover the same meter from durable workflow records."""
    state_db = str(tmp_path / "budget_state.db")
    first = _orchestrator(
        [_agent()],
        state_db=state_db,
        price_per_million={"test-model": 2.5},
        budget_max_output_tokens=100,
    )
    first.run([{"role": "user", "content": "persist budget evidence"}])
    expected = first.spend_analytics()["budget"]
    first.close()

    restored = _orchestrator(
        [_agent()],
        state_db=state_db,
        price_per_million={"test-model": 2.5},
        budget_max_output_tokens=100,
    )
    try:
        assert restored.budget_status() == expected
    finally:
        restored.close()


def test_budget_meter_reconciles_after_agent_status_change() -> None:
    """Pool mutations preserve historical spend and analytics parity."""
    priced = ModelAgent("priced_agent", "priced-model")
    fallback = ModelAgent("fallback_agent", "fallback-model")
    orchestrator = _orchestrator(
        [priced, fallback],
        price_per_million={"priced-model": 10.0},
        budget_max_cost_usd=1.0,
    )
    orchestrator._replace_workflow_run(
        {
            "workflow_run_id": "run_before_disable",
            "prompt_text": "",
            "trace": [{"agent_id": priced.id, "output": "priced output"}],
        }
    )
    before = orchestrator.budget_status()
    orchestrator.patch_agent("default", priced.id, {"status": "disabled"})
    assert orchestrator.budget_status() == before
    orchestrator.remove_agent("default", priced.id)

    assert orchestrator.budget_status() == before == orchestrator.spend_analytics()["budget"]


def test_replacing_a_run_does_not_accumulate_fractional_cost_drift() -> None:
    """Repeated replacements retain exact decimal cost accounting."""
    agents = [ModelAgent("agent_one", "model-one"), ModelAgent("agent_two", "model-two")]
    orchestrator = _orchestrator(
        agents,
        price_per_million={"model-one": 0.1, "model-two": 0.2},
        budget_max_cost_usd=1.0,
    )
    for index in range(10_000):
        agent = agents[index % 2]
        orchestrator._replace_workflow_run(
            {
                "workflow_run_id": "replaced_run",
                "prompt_text": "",
                "trace": [
                    {
                        "agent_id": agent.id,
                        "output": "x",
                        "usage": {"completion_tokens": 1},
                    }
                ],
            }
        )

    assert orchestrator.budget_status() == orchestrator.spend_analytics()["budget"]
    assert orchestrator.budget_status()["spent_cost_usd"] == 0.0000002


def test_http_over_budget_returns_429() -> None:
    token = "budget_token"
    orchestrator = _orchestrator([_agent()], budget_max_output_tokens=1)
    orchestrator.run([{"role": "user", "content": "prime the budget over the cap"}])  # now exceeded

    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps({"model": "test-model", "messages": [{"role": "user", "content": "blocked"}]}).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method="POST",
    )
    try:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status, body = response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status, body = exc.code, json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()

    assert status == 429
    assert body["error"]["code"] == "budget_exceeded"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
