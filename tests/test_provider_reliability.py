"""Provider reliability: transient-only retry with backoff, cross-agent failover, circuit breaker.

These exercise the previously untested resilience path of the orchestration engine —
the capability a model-orchestration gateway is bought for.
"""

from __future__ import annotations

from pathlib import Path
import socket
import sys
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ModelClient,
    TRANSIENT_HTTP_STATUS,
    is_transient_error,
)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://provider.example/chat/completions", code, "err", None, None)


def test_transient_classification_matches_status_and_network_errors() -> None:
    for code in (408, 409, 425, 429, 500, 502, 503, 504):
        assert code in TRANSIENT_HTTP_STATUS
        assert is_transient_error(_http_error(code)), f"{code} should be transient"
    for code in (400, 401, 403, 404, 422):
        assert not is_transient_error(_http_error(code)), f"{code} must not be retried"
    assert is_transient_error(urllib.error.URLError("dns"))
    assert is_transient_error(TimeoutError("read timeout"))
    assert is_transient_error(socket.timeout("slow"))
    assert not is_transient_error(ValueError("bad json"))


def test_retry_recovers_from_transient_failures_with_backoff() -> None:
    delays: list[float] = []

    class FlakyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=3, retry_backoff=0.1)
            self._sleep = delays.append  # capture backoff instead of sleeping
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict) -> str:  # type: ignore[override]
            self.attempts += 1
            if self.attempts < 3:
                raise _http_error(503)
            return "recovered"

    client = FlakyClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1", api_key_env="X")
    result = client._send_with_retry(agent, {"model": "gpt"})
    assert result == "recovered"
    assert client.attempts == 3  # 2 failures + 1 success
    assert len(delays) == 2  # one backoff between each retry
    assert all(0.0 <= d <= client.retry_backoff_cap for d in delays)


def test_permanent_error_is_not_retried() -> None:
    class BadRequestClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=5, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict) -> str:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(400)

    client = BadRequestClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1", api_key_env="X")
    raised = False
    try:
        client._send_with_retry(agent, {"model": "gpt"})
    except RuntimeError:
        raised = True
    assert raised
    assert client.attempts == 1  # 400 is a caller error: exactly one attempt, no retry


class _AgentDownClient(ModelClient):
    """Fails for a chosen agent id, succeeds for the rest."""

    def __init__(self, down_id: str) -> None:
        super().__init__(retry_backoff=0.0)
        self.down_id = down_id
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls.append(agent.id)
        if agent.id == self.down_id:
            raise RuntimeError(f"{agent.id} unavailable")
        return f"[{agent.id}] answer"


def _two_worker_orchestrator(down_id: str) -> tuple[TaskOrchestrator, _AgentDownClient]:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning", "writing"), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning", "writing"), priority=1),
    ]
    client = _AgentDownClient(down_id)
    return TaskOrchestrator(agents, client=client), client


def test_failover_to_backup_agent_when_primary_fails() -> None:
    orchestrator, client = _two_worker_orchestrator(down_id="primary_worker")
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    assert result["answer"] == "[backup_worker] answer"
    row = result["trace"][0]
    assert row["served_agent_id"] == "backup_worker"
    assert row["failover_from"] == "primary_worker"
    assert client.calls == ["primary_worker", "backup_worker"]  # tried primary first, then failed over


class _SlowOrFastClient(ModelClient):
    """Slow primary + fast peer in the same model_group; race must prefer first valid."""

    def __init__(self) -> None:
        super().__init__(retry_backoff=0.0)
        self.calls: list[str] = []
        self._lock = __import__("threading").Lock()

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        with self._lock:
            self.calls.append(agent.id)
        if agent.id == "slow_replica":
            __import__("time").sleep(0.25)
            return "[slow_replica] late"
        if agent.id == "fast_replica":
            return "[fast_replica] first"
        raise RuntimeError(f"unexpected agent {agent.id}")


def test_race_equivalent_model_group_returns_first_valid_completion() -> None:
    """Issue #102: same model_group peers race; first valid completion wins (not sequential tail latency)."""
    agents = [
        ModelAgent(
            "slow_replica",
            "shared-model",
            tags=("reasoning", "writing"),
            priority=5,
            model_group="gateway_pool_a",
        ),
        ModelAgent(
            "fast_replica",
            "shared-model",
            tags=("reasoning", "writing"),
            priority=4,
            model_group="gateway_pool_a",
        ),
    ]
    client = _SlowOrFastClient()
    orchestrator = TaskOrchestrator(agents, client=client)
    started = __import__("time").perf_counter()
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    elapsed = __import__("time").perf_counter() - started
    assert result["answer"] == "[fast_replica] first"
    assert result["trace"][0]["served_agent_id"] == "fast_replica"
    # Both peers should have been attempted (race), not sequential wait for slow then fast only.
    assert set(client.calls) == {"slow_replica", "fast_replica"}
    # Sequential would wait ~0.25s on slow first; race should finish near fast latency.
    assert elapsed < 0.20


def test_ungrouped_agents_do_not_race() -> None:
    """Distinct ungrouped workers stay sequential failover (preserve role diversity)."""
    orchestrator, client = _two_worker_orchestrator(down_id="primary_worker")
    # Neither agent has model_group; sequential path only.
    assert all(not agent.model_group for agent in orchestrator.agents)
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    assert client.calls == ["primary_worker", "backup_worker"]
    assert result["trace"][0]["served_agent_id"] == "backup_worker"


def test_all_agents_failing_raises_after_trying_every_candidate() -> None:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning",)),
        ModelAgent("backup_worker", "mock", tags=("reasoning",)),
    ]

    class AllDown(ModelClient):
        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
            raise RuntimeError("everything is down")

    orchestrator = TaskOrchestrator(agents, client=AllDown())
    raised = False
    try:
        orchestrator.route_once([{"role": "user", "content": "route this"}])
    except RuntimeError as exc:
        raised = True
        assert "candidate agents failed" in str(exc)
    assert raised


def test_circuit_breaker_opens_then_skips_dead_agent() -> None:
    orchestrator, client = _two_worker_orchestrator(down_id="primary_worker")
    primary = orchestrator._agent("primary_worker")

    # Each invoke fails on primary then succeeds on backup; primary accrues failures.
    for _ in range(orchestrator.circuit_failure_threshold):
        output, served, _usage = orchestrator._invoke(
            primary, [{"role": "system", "content": "Role: worker"}], text="task", role="worker"
        )
        assert served == "backup_worker"

    assert orchestrator._circuit_open("primary_worker") is True
    # Once open, the dead agent is dropped from the candidate list entirely.
    candidates = orchestrator._failover_candidates(primary, "task", "worker")
    assert [a.id for a in candidates] == ["backup_worker"]


def test_circuit_breaker_resets_after_cooldown() -> None:
    orchestrator, _ = _two_worker_orchestrator(down_id="primary_worker")
    orchestrator.circuit_reset_seconds = 0.0  # cooldown elapses immediately
    for _ in range(orchestrator.circuit_failure_threshold):
        orchestrator._record_failure("primary_worker")
    # With a zero cooldown the breaker allows a probe again.
    assert orchestrator._circuit_open("primary_worker") is False


def test_success_clears_prior_failures() -> None:
    orchestrator, _ = _two_worker_orchestrator(down_id="primary_worker")
    orchestrator._record_failure("primary_worker")
    orchestrator._record_failure("primary_worker")
    orchestrator._record_success("primary_worker")
    assert orchestrator._circuit_open("primary_worker") is False
    assert "primary_worker" not in orchestrator._circuit


def test_mock_path_is_unchanged_no_failover_no_circuit_state() -> None:
    # Regression guard: the default mock path must behave exactly as before —
    # single attempt, no failover metadata, no circuit state recorded.
    orchestrator = TaskOrchestrator([ModelAgent("solo_worker", "mock", tags=("reasoning", "writing"))])
    result = orchestrator.route_once([{"role": "user", "content": "hello"}])
    assert result["mode"] == "route"
    assert "served_agent_id" not in result["trace"][0]
    assert "failover_from" not in result["trace"][0]
    assert orchestrator._circuit == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")


def test_role_temperature_defaults_differ_by_paper_role() -> None:
    from contextual_orchestrator.orchestrator import OrchestrationPolicy

    policy = OrchestrationPolicy()
    assert policy.temperature_for_role("verifier") < policy.temperature_for_role("worker")
    snap = policy.as_dict()
    assert "role_temperature" in snap


def test_race_uses_worker_role_temperature() -> None:
    class TempClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(retry_backoff=0.0)
            self.temps: list[float] = []

        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
            self.temps.append(temperature)
            return f"[{agent.id}]"

    agents = [
        ModelAgent("rep_one", "m", tags=("reasoning", "writing"), priority=5, model_group="gateway_pool_a"),
        ModelAgent("rep_two", "m", tags=("reasoning", "writing"), priority=4, model_group="gateway_pool_a"),
    ]
    client = TempClient()
    TaskOrchestrator(agents, client=client).route_once([{"role": "user", "content": "x"}])
    assert client.temps
    assert all(t == 0.2 for t in client.temps)  # worker default
