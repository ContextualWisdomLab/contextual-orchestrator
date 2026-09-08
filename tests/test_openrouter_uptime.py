"""OpenRouter uptime collector: empirical window mass, prior-only updates."""

from __future__ import annotations

import sys
import threading
import time
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import openrouter_uptime as uptime_module
from contextual_orchestrator.model_group import ModelGroupRouter
from contextual_orchestrator.openrouter_uptime import (
    OpenRouterUptimeCollector,
)
from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


def _agents() -> list[ModelAgent]:
    """Provide one telemetry-eligible member and one negative control."""
    return [
        ModelAgent("openrouter_member", "org/model-a", provider_name="openrouter"),
        ModelAgent("other_provider_member", "model-b", provider_name="bytez"),
    ]


def _collectors(uptime: float | None):
    """Keep transport and quality ledgers observable without fetching a provider."""
    group_router = ModelGroupRouter()
    quality_router = ModelGroupRouter()
    for agent in _agents():
        group_router.register_member(agent.id)
        quality_router.register_member(agent.id)
    before_group = {a.id: group_router.member_report(a.id) for a in _agents()}
    collector = OpenRouterUptimeCollector(
        _agents(),
        group_router,
        interval_seconds=0.05,
        startup_delay_seconds=0.05,
    )
    collector._fetch_uptime = lambda model_id: uptime  # type: ignore[method-assign]
    return collector, group_router, quality_router, before_group


def test_start_without_openrouter_agents_is_inert() -> None:
    """No openrouter members means no thread and no evidence writes."""
    group_router = ModelGroupRouter()
    plain = [ModelAgent("general_agent", "mock-planner", tags=("reasoning",))]
    collector = OpenRouterUptimeCollector(plain, group_router)
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


@pytest.mark.parametrize("uptime", [0.0, 50.0, 100.0])
@pytest.mark.parametrize("judged", [False, True])
def test_availability_poll_cannot_change_answer_quality(uptime, judged):
    """Availability-only evidence must leave both cold and judged quality rows intact."""
    collector, group_router, quality_router, _before_group = _collectors(uptime)
    member_id = _agents()[0].id
    reference = ModelGroupRouter()
    reference.register_member(member_id)
    for router in (quality_router, reference):
        if judged:
            router.observe_success(member_id, 1.0)
            router.observe_failure(member_id)
    before_quality = quality_router.snapshot()
    for _ in range(3):
        collector._poll_agent(_agents()[0])
    assert quality_router.snapshot() == before_quality
    for router in (quality_router, reference):
        router.observe_success(member_id, 1.0)
    assert quality_router.member_report(member_id) == reference.member_report(member_id)
    assert sum(collector.window_evidence(member_id)) == 3
    assert group_router.member_observation_count(member_id) == 0


def test_availability_does_not_reverse_judged_member_order(monkeypatch):
    """Fixed judged outcomes retain their order despite opposite uptime histories."""
    monkeypatch.setattr(OpenRouterUptimeCollector, "start", lambda _self: None)
    agents = [
        ModelAgent("judged_strong", "mock", group_name="quality_fixture_group", provider_name="openrouter"),
        ModelAgent("judged_weak", "mock", group_name="quality_fixture_group", provider_name="openrouter"),
    ]
    gateway = TaskOrchestrator(agents)
    try:
        for agent, accepted in zip(agents, (8, 2), strict=True):
            for _ in range(accepted):
                gateway._quality_router.observe_success(agent.id, 1.0)
            for _ in range(10 - accepted):
                gateway._quality_router.observe_failure(agent.id)
        before = gateway._quality_router.snapshot()
        assert gateway._refine_partition(agents, "worker") == agents
        for agent, uptime in zip(agents, (0.0, 100.0), strict=True):
            monkeypatch.setattr(gateway._openrouter_collector, "_fetch_uptime", lambda _model, value=uptime: value)
            for _ in range(50):
                gateway._openrouter_collector._poll_agent(agent)
        assert gateway._refine_partition(agents, "worker") == agents
        assert gateway._quality_router.snapshot() == before
    finally:
        gateway.close()


def test_transport_refresh_does_not_import_answer_benchmark_prior(monkeypatch):
    """A substituted quality prior must not change the transport ledger's neutral base."""
    agent = ModelAgent("openrouter_member", "mock", provider_name="openrouter")
    monkeypatch.setattr(uptime_module, "resolve_quality_prior", lambda _member: (7.0, 3.0), raising=False)
    group_router, reference = ModelGroupRouter(), ModelGroupRouter()
    for router in (group_router, reference):
        router.observe_success(agent.id, 1.0)
        router.observe_failure(agent.id)
    collector = OpenRouterUptimeCollector([agent], group_router)
    collector._fetch_uptime = lambda _model: 100.0
    collector._poll_agent(agent)
    reference.update_prior(agent.id, 2.0, 1.0)
    assert group_router.member_report(agent.id) == reference.member_report(agent.id)


@pytest.mark.parametrize("raw_value", [
    "NaN", "Infinity", "-Infinity", "1e400", "-1e400",
    "true", "false", '"99.5"', '"NaN"', "-0.01", "100.01", "{}", "[]",
])
@pytest.mark.parametrize("placement", ["only", "first", "last"])
def test_invalid_endpoint_percentage_cannot_update_evidence(monkeypatch, raw_value, placement):
    """Malformed telemetry cannot become window mass, regardless of endpoint order."""
    endpoint_rows = ['{"uptime_last_30m":' + raw_value + '}']
    if placement == "first":
        endpoint_rows.append('{"uptime_last_30m":50}')
    elif placement == "last":
        endpoint_rows.insert(0, '{"uptime_last_30m":50}')
    response_body = ('{"data":{"endpoints":[' + ','.join(endpoint_rows) + ']}}').encode()
    http_response = BytesIO(response_body)
    monkeypatch.setattr(uptime_module.urllib.request, "urlopen", lambda *_args, **_kwargs: http_response)
    group_router = ModelGroupRouter()
    agent = _agents()[0]
    group_router.observe_success(agent.id, 0.2)
    group_router.observe_failure(agent.id)
    report_before = group_router.snapshot()
    collector = OpenRouterUptimeCollector([agent], group_router)

    collector._poll_agent(agent)

    assert http_response.closed
    assert collector.window_evidence(agent.id) == (0.0, 0.0)
    assert group_router.snapshot() == report_before


@pytest.mark.parametrize(("raw_endpoints", "expected_mass"), [
    ('[{"uptime_last_30m":0}]', (0.0, 1.0)),
    ('[{"uptime_last_30m":50}]', (0.5, 0.5)),
    ('[{"uptime_last_30m":100}]', (1.0, 0.0)),
    ('[{"uptime_last_30m":null},{},{"uptime_last_30m":99.5}]', (0.995, 0.005)),
    ('[{"uptime_last_30m":25},{"uptime_last_30m":75}]', (0.75, 0.25)),
    ('[{"uptime_last_30m":null},{}]', (0.0, 0.0)),
    ('[]', (0.0, 0.0)),
])
def test_endpoint_percentage_parsing_preserves_valid_and_absent_values(monkeypatch, raw_endpoints, expected_mass):
    """Valid percentages retain existing window accounting; absent values add nothing."""
    http_response = BytesIO(('{"data":{"endpoints":' + raw_endpoints + '}}').encode())
    monkeypatch.setattr(uptime_module.urllib.request, "urlopen", lambda *_args, **_kwargs: http_response)
    group_router = ModelGroupRouter()
    agent = _agents()[0]
    collector = OpenRouterUptimeCollector([agent], group_router)

    collector._poll_agent(agent)

    assert http_response.closed
    assert collector.window_evidence(agent.id) == pytest.approx(expected_mass)
    assert group_router.member_observation_count(agent.id) == 0


@pytest.mark.parametrize(("model_id", "encoded_model"), [
    ("openai/gpt-4o", "openai/gpt-4o"),
    ("org/model:free", "org/model%3Afree"),
    ("org name/model?#%", "org%20name/model%3F%23%25"),
    ("조직/모델", "%EC%A1%B0%EC%A7%81/%EB%AA%A8%EB%8D%B8"),
    ("org/model%2Fname", "org/model%252Fname"),
])
def test_endpoint_request_preserves_author_slug_boundary(monkeypatch, model_id, encoded_model):
    """Only the documented author/slug separator remains structural in the URL."""
    http_response = BytesIO(b'{"data":{"endpoints":[{"uptime_last_30m":99.5}]}}')

    def checked_open(request, *, timeout):
        """Check the real assembled request without contacting a provider."""
        assert request.full_url == f"https://openrouter.ai/api/v1/models/{encoded_model}/endpoints"
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") is None
        assert timeout == 10.0
        return http_response

    monkeypatch.setattr(uptime_module.urllib.request, "urlopen", checked_open)
    collector = OpenRouterUptimeCollector([], ModelGroupRouter())

    assert collector._fetch_uptime(model_id) == 99.5
    assert http_response.closed


@pytest.mark.parametrize("model_id", [
    "", "model", "/model", "org/", "org/model/extra", "//example.invalid/model",
    "https://example.invalid/model", "../model", "org/..", "./model", "org/.",
])
def test_malformed_model_path_never_reaches_transport(monkeypatch, model_id):
    """Absent or traversal path components cannot become endpoint requests."""
    def reject_open(*_args, **_kwargs):
        """Make any unexpected transport request a visible contract failure."""
        pytest.fail("malformed model ID reached transport")

    monkeypatch.setattr(uptime_module.urllib.request, "urlopen", reject_open)
    collector = OpenRouterUptimeCollector([], ModelGroupRouter())

    assert collector._fetch_uptime(model_id) is None


if __name__ == "__main__":
    test_start_without_openrouter_agents_is_inert()
    test_poll_folds_one_window_of_measured_mass()
    test_non_openrouter_agents_are_never_polled()
    test_unavailable_uptime_poll_is_a_no_op()
    test_background_loop_accumulates_and_stop_joins()
    test_update_prior_contract_preserves_observation_counts()
    test_update_prior_rejects_invalid_components()
    print("ok")
