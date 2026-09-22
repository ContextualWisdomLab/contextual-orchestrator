"""Observed-outcome health quarantine for served-request candidate selection.

Evidence: 101 sanitized Noema sidecar artifacts (deployed pin 767e67f) showed
the same agent slow-failing (RemoteDisconnected / HTTP 504, p50 ~265-302 s)
repeatedly within one run, while the legacy breaker's 30 s reset expired
before a single ~300 s failure finished. These contracts pin the repair: a
served request's slow failure must influence the next request's candidate
order, repeated slow failures quarantine the agent for a cooldown longer than
one failing attempt, and a half-open probe recovers it.
"""

from __future__ import annotations

import http.client
import io
import logging
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ModelClient,
    classify_health_failure,
)
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import OBSERVED_HEALTH_QUARANTINE_SETTING  # noqa: E402
from contextual_orchestrator.provider_errors import ProviderUpstreamError  # noqa: E402
from contextual_orchestrator.review_gateway import register_review_credentials  # noqa: E402

_LOGGER_NAME = "contextual_orchestrator.orchestrator"


@contextmanager
def _captured_logs(level: int) -> Iterator[io.StringIO]:
    """Attach an isolated handler to the orchestrator logger only."""
    logger = logging.getLogger(_LOGGER_NAME)
    previous_level, previous_propagate = logger.level, logger.propagate
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    try:
        yield buffer
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _gateway_timeout(agent_id: str) -> ProviderUpstreamError:
    return ProviderUpstreamError(
        agent_id=agent_id,
        model="mock",
        error_code="provider_timeout",
        message="provider timed out",
        client_status=504,
        provider_status=504,
        retryable=True,
    )


class _ScriptedClient(ModelClient):
    """Fail the agents listed in ``down`` with a slow-class 504; record every call."""

    def __init__(self) -> None:
        super().__init__()
        self.down: set[str] = set()
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls.append(agent.id)
        if agent.id in self.down:
            raise _gateway_timeout(agent.id)
        return f"answer from {agent.id}"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _pool(enabled: bool = True) -> tuple[TaskOrchestrator, _ScriptedClient, _Clock]:
    agents = [
        ModelAgent("slow_worker", "mock", tags=("reasoning", "writing"), priority=5),
        ModelAgent("steady_worker", "mock", tags=("reasoning", "writing"), priority=1),
    ]
    client = _ScriptedClient()
    orchestrator = TaskOrchestrator(
        agents,
        client=client,
        tool_retry_backoff_seconds=0.0,
        observed_health_quarantine=enabled,
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.tool_retry_attempts = 0
    clock = _Clock()
    orchestrator._circuit_clock = clock
    return orchestrator, client, clock


def _serve(orchestrator: TaskOrchestrator) -> str:
    primary = orchestrator._agent("slow_worker")
    _output, served, _model, _usage = orchestrator._invoke(
        primary, [{"role": "system", "content": "Role: worker"}], text="task", role="worker"
    )
    return served


def _order(orchestrator: TaskOrchestrator) -> list[str]:
    primary = orchestrator._agent("slow_worker")
    return [agent.id for agent in orchestrator._failover_candidates(primary, "task", "worker")]


def test_failure_classes_separate_slow_post_send_from_fast_rejections() -> None:
    assert classify_health_failure(_gateway_timeout("a")) == "slow_transport"
    assert classify_health_failure(http.client.RemoteDisconnected("closed")) == "slow_transport"
    assert classify_health_failure(TimeoutError("read timed out")) == "slow_transport"
    not_found = ProviderUpstreamError(
        agent_id="a", model="m", error_code="model_not_found", message="x",
        client_status=404, provider_status=404,
    )
    assert classify_health_failure(not_found) == "fast"
    assert classify_health_failure(RuntimeError("opaque")) == "fast"


def test_wrapped_post_send_failures_stay_slow_class() -> None:
    """ModelClient wraps a dropped connection as provider_outcome_unknown before _invoke sees it."""
    for code in ("provider_outcome_unknown", "model_timeout"):
        wrapped = ProviderUpstreamError(
            agent_id="a", model="m", error_code=code, message="x",
            client_status=502, provider_status=None, retryable=False,
        )
        assert classify_health_failure(wrapped) == "slow_transport", code


def test_served_slow_failure_demotes_agent_for_the_next_request() -> None:
    orchestrator, client, _clock = _pool()
    client.down.add("slow_worker")

    assert _serve(orchestrator) == "steady_worker"  # request N: slow failure recorded
    assert client.calls == ["slow_worker", "steady_worker"]

    # One slow failure never quarantines ...
    assert orchestrator._circuit_open("slow_worker") is False
    # ... but request N+1 tries the healthy sibling first and never pays the
    # ~300 s failure again when that sibling succeeds.
    assert _order(orchestrator) == ["steady_worker", "slow_worker"]
    client.calls.clear()
    assert _serve(orchestrator) == "steady_worker"
    assert client.calls == ["steady_worker"]


def test_single_fast_failure_neither_quarantines_nor_demotes() -> None:
    orchestrator, _client, _clock = _pool()
    orchestrator._record_failure("slow_worker", failure_class="fast")
    assert orchestrator._circuit_open("slow_worker") is False
    assert _order(orchestrator) == ["slow_worker", "steady_worker"]


def test_repeated_slow_failures_quarantine_past_one_failing_attempt_then_recover() -> None:
    orchestrator, client, clock = _pool()
    orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    with _captured_logs(logging.INFO) as buffer:
        orchestrator._record_failure("slow_worker", failure_class="slow_transport")
        opened = buffer.getvalue()
    assert "circuit_opened agent_id=slow_worker" in opened
    assert "failure_class=slow_transport" in opened
    assert orchestrator._circuit_open("slow_worker") is True
    assert _order(orchestrator) == ["steady_worker"]

    # The legacy 30 s reset is shorter than one ~300 s slow failure; the
    # slow-class cooldown must outlast it.
    clock.now += 301.0
    assert orchestrator._circuit_open("slow_worker") is True

    clock.now += orchestrator.slow_failure_cooldown_seconds
    with _captured_logs(logging.INFO) as buffer:
        assert orchestrator._circuit_open("slow_worker") is False
        assert "circuit_half_open agent_id=slow_worker" in buffer.getvalue()
    # Half-open: eligible again, but tried only after healthy siblings.
    assert _order(orchestrator) == ["steady_worker", "slow_worker"]

    client.down.clear()
    client.down.add("steady_worker")
    with _captured_logs(logging.INFO) as buffer:
        assert _serve(orchestrator) == "slow_worker"  # the half-open probe succeeds
        assert "circuit_recovered agent_id=slow_worker" in buffer.getvalue()
    assert orchestrator.circuit_health_snapshot()["slow_worker"]["state"] == "closed"


def test_half_open_failure_reopens_with_escalated_bounded_cooldown() -> None:
    orchestrator, _client, clock = _pool()
    for _ in range(2):
        orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    first = orchestrator.circuit_health_snapshot()["slow_worker"]["cooldown_seconds"]
    clock.now += first
    assert orchestrator._circuit_open("slow_worker") is False  # half-open
    orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    assert orchestrator._circuit_open("slow_worker") is True
    second = orchestrator.circuit_health_snapshot()["slow_worker"]["cooldown_seconds"]
    assert second == 2 * first
    for _ in range(10):
        clock.now += orchestrator.circuit_health_snapshot()["slow_worker"]["cooldown_seconds"]
        assert orchestrator._circuit_open("slow_worker") is False
        orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    capped = orchestrator.circuit_health_snapshot()["slow_worker"]["cooldown_seconds"]
    assert capped == orchestrator.circuit_max_cooldown_seconds


def test_observed_failure_rate_quarantines_an_intermittently_failing_agent() -> None:
    orchestrator, _client, _clock = _pool()
    # Never three consecutive failures, but most recent outcomes failed.
    for outcome in ("fail", "ok", "fail", "fail", "ok", "fail", "fail"):
        if outcome == "fail":
            orchestrator._record_failure("slow_worker", failure_class="fast")
        else:
            orchestrator._record_success("slow_worker")
    assert orchestrator._circuit_open("slow_worker") is True
    snapshot = orchestrator.circuit_health_snapshot()["slow_worker"]
    assert snapshot["window_failure_rate"] >= orchestrator.circuit_failure_rate_threshold


def test_all_quarantined_pool_falls_back_to_least_recently_failed_member() -> None:
    orchestrator, _client, clock = _pool()
    for _ in range(2):
        orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    clock.now += 5.0
    for _ in range(2):
        orchestrator._record_failure("steady_worker", failure_class="slow_transport")
    with _captured_logs(logging.WARNING) as buffer:
        order = _order(orchestrator)
        fallback = buffer.getvalue()
    assert order == ["slow_worker", "steady_worker"]  # never an empty pool
    assert "circuit_all_open_fallback candidate_count=2 selected_agent_id=slow_worker" in fallback


def test_concurrent_slow_failures_open_the_circuit_exactly_once() -> None:
    orchestrator, _client, _clock = _pool()
    calls = 16
    barrier = threading.Barrier(calls, timeout=2.0)

    def record(_index: int) -> None:
        barrier.wait()
        orchestrator._record_failure("slow_worker", failure_class="slow_transport")

    with _captured_logs(logging.WARNING) as buffer:
        with ThreadPoolExecutor(max_workers=calls) as pool:
            list(pool.map(record, range(calls)))
        output = buffer.getvalue()
    assert output.count("circuit_opened agent_id=slow_worker") == 1
    assert orchestrator._circuit["slow_worker"]["failures"] == float(calls)
    snapshot = orchestrator.circuit_health_snapshot()["slow_worker"]
    assert snapshot["state"] == "open"
    assert snapshot["consecutive_failures"] == calls


def test_default_orchestrator_keeps_the_legacy_breaker_policy() -> None:
    """Without the operator opt-in, weights, cooldowns and demotion stay legacy 3/30."""
    orchestrator, client, clock = _pool(enabled=False)
    assert TaskOrchestrator([ModelAgent("solo_worker", "mock")]).observed_health_quarantine is False
    client.down.add("slow_worker")
    _serve(orchestrator)
    assert _order(orchestrator) == ["slow_worker", "steady_worker"]  # no demotion
    orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    assert orchestrator._circuit_open("slow_worker") is False  # two slow != three strikes
    orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    assert orchestrator._circuit_open("slow_worker") is True
    clock.now += orchestrator.circuit_reset_seconds
    assert orchestrator._circuit_open("slow_worker") is False
    orchestrator._record_failure("slow_worker", failure_class="slow_transport")
    assert orchestrator._circuit_open("slow_worker") is False  # counter restarts from zero


def test_health_snapshot_is_bounded_and_prompt_free() -> None:
    orchestrator, client, _clock = _pool()
    client.down.add("slow_worker")
    _serve(orchestrator)
    snapshot = orchestrator.circuit_health_snapshot()
    assert set(snapshot["slow_worker"]) == {
        "state", "model", "provider", "consecutive_failures", "weighted_score",
        "last_failure_class", "cooldown_seconds", "remaining_seconds",
        "window_size", "window_failure_rate", "open_count",
    }
    assert "task" not in repr(snapshot)
    assert orchestrator.admin_state()["routing_evidence"]["health"] == snapshot


@contextmanager
def _fresh_kv() -> Iterator[None]:
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _launcher_shaped() -> TaskOrchestrator:
    """Construct exactly as the review launcher does: no policy argument."""
    return TaskOrchestrator([ModelAgent("solo_worker", "mock")], client=ModelClient())


def test_kv_switch_is_the_single_deployable_activation_and_is_audited() -> None:
    with _fresh_kv():
        default = _launcher_shaped()
        assert (default.observed_health_quarantine, default.observed_health_quarantine_source) == (False, "default")
        register_review_credentials({OBSERVED_HEALTH_QUARANTINE_SETTING: "enabled\n"})
        with _captured_logs(logging.INFO) as buffer:
            enabled = _launcher_shaped()
        assert enabled.observed_health_quarantine is True
        assert f"observed_health_quarantine enabled=True source=kv setting={OBSERVED_HEALTH_QUARANTINE_SETTING}" in buffer.getvalue()
        policy = enabled.admin_state()["routing_evidence"]["health_policy"]
        assert policy["observed_health_quarantine"] is True and policy["source"] == "kv"
        assert policy["slow_failure_cooldown_seconds"] == 360.0
        # An explicit constructor boolean still wins over the KV value.
        assert TaskOrchestrator([ModelAgent("solo_worker", "mock")], observed_health_quarantine=False).observed_health_quarantine is False


def test_kv_switch_off_values_and_invalid_value_fail_closed() -> None:
    with _fresh_kv():
        register_credential(OBSERVED_HEALTH_QUARANTINE_SETTING, "disabled")
        off = _launcher_shaped()
        assert (off.observed_health_quarantine, off.observed_health_quarantine_source) == (False, "kv")
        register_credential(OBSERVED_HEALTH_QUARANTINE_SETTING, "maybe")
        try:
            _launcher_shaped()
        except ValueError as exc:
            assert OBSERVED_HEALTH_QUARANTINE_SETTING in str(exc)
        else:  # pragma: no cover
            raise AssertionError("an unrecognized switch value must fail construction")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
