"""OpenRouter uptime collector: empirical window mass, prior-only updates."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.model_group import ModelGroupRouter
from contextual_orchestrator.openrouter_uptime import (
    OpenRouterUptimeCollector,
)
from contextual_orchestrator.orchestrator import ModelAgent


def _agents() -> list[ModelAgent]:
    return [
        ModelAgent("openrouter_member", "org/model-a", provider_name="openrouter"),
        ModelAgent("other_provider_member", "model-b", provider_name="bytez"),
    ]


def _collectors(uptime: float | None):
    group_router = ModelGroupRouter()
    quality_router = ModelGroupRouter()
    for agent in _agents():
        group_router.register_member(agent.id)
        quality_router.register_member(agent.id)
    before_group = {a.id: group_router.member_report(a.id) for a in _agents()}
    collector = OpenRouterUptimeCollector(
        _agents(),
        group_router,
        quality_router,
        interval_seconds=0.05,
        startup_delay_seconds=0.05,
    )
    collector._fetch_uptime = lambda model_id: uptime  # type: ignore[method-assign]
    return collector, group_router, quality_router, before_group


def test_start_without_openrouter_agents_is_inert() -> None:
    """No openrouter members means no thread and no evidence writes."""
    group_router = ModelGroupRouter()
    quality_router = ModelGroupRouter()
    plain = [ModelAgent("general_agent", "mock-planner", tags=("reasoning",))]
    collector = OpenRouterUptimeCollector(plain, group_router, quality_router)
    collector.start()
    assert collector.window_evidence("general_agent") == (0.0, 0.0)
    collector.stop()


def test_poll_folds_one_window_of_measured_mass() -> None:
    """One 95% availability window adds exactly (0.95, 0.05) of evidence."""
    import pytest

    collector, group_router, _, _ = _collectors(95.0)
    agent = _agents()[0]
    report_before = group_router.member_report(agent.id)
    success_count_before = report_before["success_count"]

    collector._poll_agent(agent)

    successes, failures = collector.window_evidence(agent.id)
    assert successes == pytest.approx(0.95)
    assert failures == pytest.approx(0.05)

    # Prior refresh must not masquerade as observed outcomes.
    assert group_router.member_report(agent.id)["success_count"] == success_count_before


def test_non_openrouter_agents_are_never_polled() -> None:
    """Only openrouter-provider members receive measurements."""
    collector, _, _, _ = _collectors(100.0)
    other = _agents()[1]
    collector._poll_agent(other)
    assert collector.window_evidence(other.id) == (0.0, 0.0)


def test_unavailable_uptime_poll_is_a_no_op() -> None:
    """A failed fetch leaves ledgers and counters untouched."""
    collector, _, _, _ = _collectors(None)
    agent = _agents()[0]
    collector._poll_agent(agent)
    assert collector.window_evidence(agent.id) == (0.0, 0.0)


def test_uptime_fetch_keeps_a_fixed_network_deadline_independent_of_inference() -> None:
    """The background uptime GET keeps its own bound, unlike inference calls.

    #971 removes the *inference* client's fixed wall-clock deadline (a user
    is actively waiting on a model completion). This collector's HTTP GET is
    unrelated background telemetry on one dedicated sequential sweep thread
    that ``stop()`` cannot interrupt mid-request (Python threads cannot be
    forcibly cancelled): an unbounded fetch would let one unresponsive
    OpenRouter endpoint hang that thread forever, leaking it and
    indefinitely starving every later member of an uptime update. The fetch
    must stay bounded regardless of #971's inference-deadline policy.
    """
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"data": {"endpoints": []}}).encode()

    collector, _, _, _ = _collectors(None)
    del collector._fetch_uptime
    with patch(
        "contextual_orchestrator.openrouter_uptime.urllib.request.urlopen",
        return_value=_Response(),
    ) as opened:
        assert collector._fetch_uptime("org/model-a") is None

    timeout = opened.call_args.kwargs["timeout"]
    assert timeout is not None
    assert 0 < timeout <= 30


def test_uptime_fetch_does_not_hang_forever_on_an_unresponsive_endpoint(monkeypatch) -> None:
    """A stalled connection is bounded end-to-end, not blocked forever.

    Complements the kwarg-level assertion above by proving the timeout is
    actually enforced: a real TCP listener that accepts the connection and
    never responds must still return within a short bound instead of
    hanging the sweep thread indefinitely (which would leak that thread and
    starve every later member of an uptime update).
    """
    import contextual_orchestrator.openrouter_uptime as uptime_module

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    accepted = threading.Event()

    def accept_and_stall() -> None:
        try:
            conn, _ = server.accept()
            accepted.set()
            time.sleep(2.0)  # Accept the connection but never respond.
            conn.close()
        except OSError:
            pass

    acceptor = threading.Thread(target=accept_and_stall, daemon=True)
    acceptor.start()
    try:
        monkeypatch.setattr(uptime_module, "_UPTIME_FETCH_TIMEOUT_SECONDS", 0.3)
        monkeypatch.setattr(
            uptime_module, "_OPENROUTER_UPTIME_ORIGIN", f"http://{host}:{port}/api/v1"
        )
        collector, _, _, _ = _collectors(None)
        del collector._fetch_uptime

        started = time.monotonic()
        result = collector._fetch_uptime("org/model-a")
        elapsed = time.monotonic() - started

        assert result is None
        assert elapsed < 2.0
        assert accepted.wait(timeout=1.0)
    finally:
        server.close()
        acceptor.join(timeout=3.0)


def test_background_loop_accumulates_and_stop_joins() -> None:
    """The sweep thread runs until stop(), and stop() returns quickly."""
    collector, _, _, _ = _collectors(80.0)
    collector.start()
    deadline = time.monotonic() + 5.0
    while (
        collector.window_evidence("openrouter_member") == (0.0, 0.0)
        and time.monotonic() < deadline
    ):
        threading.Event().wait(0.01)
    first = collector.window_evidence("openrouter_member")
    assert first != (0.0, 0.0)
    started = time.monotonic()
    collector.stop()
    joined = time.monotonic() - started
    assert joined < 3.0
    # Evidence is capped to whole windows; partial mass beyond stop is fine,
    # but the thread must have terminated at least one full poll.


def test_update_prior_contract_preserves_observation_counts() -> None:
    """Router-level update_prior shifts only the prior pair, never outcomes."""
    router = ModelGroupRouter()
    router.register_member("member_a")
    router.observe_success("member_a", 0.2)
    router.observe_success("member_a", 0.3, output_tokens=100)
    router.observe_failure("member_a")
    before = router.member_report("member_a")
    assert before["success_count"] == 2 and before["failure_count"] == 1

    router.update_prior("member_a", 2.5, 7.5)
    after = router.member_report("member_a")
    assert after["success_count"] == 2
    assert after["failure_count"] == 1


def test_update_prior_rejects_invalid_components() -> None:
    """Negative or non-finite prior components are rejected outright."""
    import pytest

    router = ModelGroupRouter()
    router.register_member("member_b")
    with pytest.raises(ValueError):
        router.update_prior("member_b", -1.0, 0.0)
    with pytest.raises(ValueError):
        router.update_prior("member_b", float("nan"), 0.0)


if __name__ == "__main__":
    test_start_without_openrouter_agents_is_inert()
    test_poll_folds_one_window_of_measured_mass()
    test_non_openrouter_agents_are_never_polled()
    test_unavailable_uptime_poll_is_a_no_op()
    test_background_loop_accumulates_and_stop_joins()
    test_update_prior_contract_preserves_observation_counts()
    test_update_prior_rejects_invalid_components()
    print("ok")
