"""Lifecycle contract for OpenRouter uptime telemetry shutdown."""

from __future__ import annotations

import threading
import time

from contextual_orchestrator.model_group import ModelGroupRouter
from contextual_orchestrator.openrouter_uptime import OpenRouterUptimeCollector
from contextual_orchestrator.orchestrator import ModelAgent


def test_stop_discards_an_inflight_measurement_before_it_can_mutate_the_prior() -> None:
    """A fetch completing after stop begins must not publish stale evidence."""
    agent = ModelAgent(
        "openrouter_member",
        "org/model-a",
        provider_name="openrouter",
    )
    group_router = ModelGroupRouter()
    group_router.register_member(agent.id)
    collector = OpenRouterUptimeCollector(
        [agent],
        group_router,
        interval_seconds=60.0,
        startup_delay_seconds=0.0,
    )
    fetch_started = threading.Event()
    release_fetch = threading.Event()

    def delayed_fetch(_model_id: str) -> float:
        fetch_started.set()
        assert release_fetch.wait(timeout=2.0)
        return 100.0

    collector._fetch_uptime = delayed_fetch  # type: ignore[method-assign]
    before = group_router.snapshot()
    collector.start()
    assert fetch_started.wait(timeout=1.0)

    stopper = threading.Thread(target=collector.stop)
    stopper.start()
    deadline = time.monotonic() + 1.0
    while not collector._stop_event.is_set() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert collector._stop_event.is_set()

    release_fetch.set()
    stopper.join(timeout=1.0)
    assert not stopper.is_alive()
    assert collector.window_evidence(agent.id) == (0.0, 0.0)
    assert group_router.snapshot() == before
