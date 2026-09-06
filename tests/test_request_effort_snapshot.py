"""Request-boundary regressions for declared effort, identity, and answer records."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from contextual_orchestrator import (
    ModelAgent,
    TaskOrchestrator,
    default_role_effort_catalog,
)
from contextual_orchestrator import orchestrator as runtime_module
from contextual_orchestrator.provider_errors import ProviderUpstreamError
from contextual_orchestrator.reasoning_effort_profile import (
    EffortProfileError,
    snapshot_role_effort_catalog,
)


def _orchestrator(**kwargs):
    """Use one local worker and a uniform catalog to expose mixed request revisions."""
    catalog = {
        role: replace(profile, reasoning_effort="medium")
        for role, profile in default_role_effort_catalog().items()
    }
    orchestrator = TaskOrchestrator(
        [ModelAgent("snapshot_worker", "mock", tags=("reasoning", "writing"))],
        role_effort_catalog=catalog,
        **kwargs,
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    return orchestrator, catalog


def _change_effort(catalog, effort="high"):
    """Replace every immutable profile in the caller-owned catalog."""
    catalog.update({role: replace(profile, reasoning_effort=effort) for role, profile in catalog.items()})


def test_standalone_role_lookup_preserves_partial_catalog():
    """A single-role adapter is not a full request, even inside another gateway's scope."""
    outer, _unused_catalog = _orchestrator()
    inner, catalog = _orchestrator()
    judge_profile = replace(catalog["judge"], reasoning_effort="low")
    inner.role_effort_catalog = {"judge": judge_profile}
    try:
        assert inner._role_effort_profile("judge") is judge_profile
        assert inner._role_effort_profile("worker") is None
        with outer._request_execution_scope():
            assert inner._role_effort_profile("judge") is judge_profile
            with pytest.raises(EffortProfileError, match="catalog must bind exactly"):
                inner.complete([{"role": "user", "content": "partial catalog unit fixture"}])
            assert outer._role_effort_profile("judge").reasoning_effort == "medium"
        inner.role_effort_catalog = None
        assert inner._role_effort_profile("judge") is None
    finally:
        inner.close()
        outer.close()


@pytest.mark.parametrize(
    ("entry_point", "options"),
    [
        ("complete", {"mode": "route"}),
        ("complete", {"mode": "conduct"}),
        ("route_once", {}),
        ("conduct", {}),
        ("run", {"mode": "route"}),
    ],
)
def test_request_keeps_effort_revision_during_execution(monkeypatch, entry_point, options):
    """All calls, selection identities, and result metadata use the starting catalog."""
    orchestrator, catalog = _orchestrator()
    expected_hash = snapshot_role_effort_catalog(catalog).snapshot_hash
    expected_identity = orchestrator._psychometric_candidate_id(orchestrator.agents[0])
    received_efforts = []

    def chat(agent, messages, **kwargs):
        """Change operator settings after receiving the first request profile."""
        received_efforts.append(kwargs["effort_profile"].reasoning_effort)
        _change_effort(catalog)
        return "answer-" + received_efforts[-1]

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    messages = [{"role": "user", "content": "request revision unit fixture"}]
    try:
        result = getattr(orchestrator, entry_point)(messages, **options)
        assert received_efforts and set(received_efforts) == {"medium"}
        assert result["reasoning_effort_snapshot"]["snapshot_hash"] == expected_hash
        assert all(
            row["selection_design"]["selected_deployment_id"] == expected_identity
            for row in result["trace"]
        )
        received_efforts.clear()
        next_result = orchestrator.complete(messages, mode="route")
        assert received_efforts == ["high"]
        assert next_result["reasoning_effort_snapshot"]["snapshot_hash"] == (
            snapshot_role_effort_catalog(catalog).snapshot_hash
        )
    finally:
        orchestrator.close()


def test_inflight_effort_change_does_not_poison_original_cache_key(monkeypatch):
    """A restored catalog may replay its old answer only with the matching snapshot."""
    orchestrator, catalog = _orchestrator(cache_ttl=60)
    original = dict(catalog)
    expected_hash = snapshot_role_effort_catalog(catalog).snapshot_hash
    calls = []

    def chat(agent, messages, *, effort_profile):
        """Return the received effort while changing the next request's settings."""
        calls.append(effort_profile.reasoning_effort)
        _change_effort(catalog)
        return "answer-" + effort_profile.reasoning_effort

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    messages = [{"role": "user", "content": "cached revision unit fixture"}]
    try:
        first = orchestrator.complete(messages, mode="route")
        changed = orchestrator.complete(messages, mode="route")
        catalog.update(original)
        replayed = orchestrator.complete(messages, mode="route")
        assert calls == ["medium", "high"]
        assert [first["cache_status"], changed["cache_status"], replayed["cache_status"]] == [
            "miss", "miss", "hit"
        ]
        assert first["answer"] == replayed["answer"] == "answer-medium"
        assert first["reasoning_effort_snapshot"]["snapshot_hash"] == expected_hash
        assert replayed["reasoning_effort_snapshot"]["snapshot_hash"] == expected_hash
    finally:
        orchestrator.close()


def test_batch_keeps_starting_effort_and_detaches_each_record(monkeypatch):
    """Worker output, pending/final metadata, and sibling rows keep one batch revision."""
    orchestrator, catalog = _orchestrator()
    expected_hash = snapshot_role_effort_catalog(catalog).snapshot_hash

    def batch_chat(agent, requests, *, effort_profile):
        """Change settings before completed batch rows are persisted."""
        _change_effort(catalog)
        return {
            request_id: {"content": "answer-" + effort_profile.reasoning_effort}
            for request_id in requests
        }

    monkeypatch.setattr(orchestrator.client, "batch_chat", batch_chat)
    try:
        records = orchestrator.batch_route(["first unit fixture", "second unit fixture"])
        assert [row["answer"] for row in records] == ["answer-medium", "answer-medium"]
        assert all(row["reasoning_effort_snapshot"]["snapshot_hash"] == expected_hash for row in records)
        records[0]["reasoning_effort_snapshot"]["role_profiles"]["worker"]["reasoning_effort"] = "low"
        assert records[1]["reasoning_effort_snapshot"]["role_profiles"]["worker"]["reasoning_effort"] == "medium"
    finally:
        orchestrator.close()


def test_interleaved_streams_do_not_share_effort_context(monkeypatch):
    """Suspended streams retain their own revision without leaking it to later calls."""
    orchestrator, catalog = _orchestrator()
    expected_hash = snapshot_role_effort_catalog(catalog).snapshot_hash
    expected_identity = orchestrator._psychometric_candidate_id(orchestrator.agents[0])

    def stream_chat(agent, messages, *, effort_profile):
        """Yield twice so two independently started streams can be interleaved."""
        yield effort_profile.reasoning_effort + "-first"
        yield effort_profile.reasoning_effort + "-last"

    monkeypatch.setattr(orchestrator.client, "stream_chat", stream_chat)
    messages = [{"role": "user", "content": "interleaved stream unit fixture"}]
    first_stream = orchestrator.stream_route(messages, workflow_run_id="first_snapshot_stream")
    second_stream = None
    try:
        assert next(first_stream) == "medium-first"
        _change_effort(catalog)
        second_stream = orchestrator.stream_route(messages, workflow_run_id="second_snapshot_stream")
        assert next(second_stream) == "high-first"
        assert list(first_stream) == ["medium-last"]
        assert list(second_stream) == ["high-last"]
        first = orchestrator.get_workflow_run("first_snapshot_stream")
        second = orchestrator.get_workflow_run("second_snapshot_stream")
        assert first["reasoning_effort_snapshot"]["snapshot_hash"] == expected_hash
        assert first["trace"][0]["selection_design"]["selected_deployment_id"] == expected_identity
        assert second["reasoning_effort_snapshot"]["snapshot_hash"] == snapshot_role_effort_catalog(catalog).snapshot_hash
    finally:
        first_stream.close()
        if second_stream is not None:
            second_stream.close()
        orchestrator.close()


def test_concurrent_requests_keep_independent_catalogs_without_serializing(monkeypatch):
    """A later request can finish under new settings while the first worker is blocked."""
    orchestrator, catalog = _orchestrator()
    old_hash = snapshot_role_effort_catalog(catalog).snapshot_hash
    old_policy = orchestrator.policy
    started, release = Event(), Event()

    def chat(agent, messages, *, effort_profile):
        """Hold the first provider double while the other request completes."""
        if messages[-1]["content"] == "first concurrent fixture":
            started.set()
            assert release.wait(5), "second request was serialized behind the first"
        return effort_profile.reasoning_effort

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(orchestrator.complete, [{"role": "user", "content": "first concurrent fixture"}], "route")
            try:
                assert started.wait(5)
                _change_effort(catalog)
                orchestrator.policy = replace(old_policy, route_p95_seconds=9)
                second_future = pool.submit(orchestrator.complete, [{"role": "user", "content": "second concurrent fixture"}], "route")
                second = second_future.result(timeout=5)
            finally:
                release.set()
            first = first_future.result(timeout=5)
        assert first["answer"] == "medium"
        assert first["reasoning_effort_snapshot"]["snapshot_hash"] == old_hash
        assert first["policy_snapshot"] == old_policy.as_dict()
        assert second["answer"] == "high"
        assert second["reasoning_effort_snapshot"]["snapshot_hash"] == snapshot_role_effort_catalog(catalog).snapshot_hash
        assert second["policy_snapshot"] == orchestrator.policy.as_dict()
        assert second["policy_snapshot"]["route_p95_seconds"] == 9
    finally:
        orchestrator.close()


def test_failed_request_restores_effort_context(monkeypatch):
    """An exception must not pin the failed request's revision onto its successor."""
    orchestrator, catalog = _orchestrator()

    def interrupted(*args, **kwargs):
        """Change configuration, then fail inside the scoped dispatch boundary."""
        _change_effort(catalog)
        orchestrator.policy = replace(orchestrator.policy, route_p95_seconds=9)
        raise RuntimeError("fixture interruption")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(orchestrator, "_dispatch", interrupted)
            with pytest.raises(RuntimeError, match="fixture interruption"):
                orchestrator.complete([{"role": "user", "content": "interrupted fixture"}], mode="route")
        next_result = orchestrator.complete([{"role": "user", "content": "successor fixture"}], mode="route")
        assert next_result["reasoning_effort_snapshot"]["snapshot_hash"] == snapshot_role_effort_catalog(catalog).snapshot_hash
        assert orchestrator.policy.route_p95_seconds == 9
        assert next_result["policy_snapshot"] == orchestrator.policy.as_dict()
    finally:
        orchestrator.close()


@pytest.mark.parametrize("termination", ["close", "provider_error"])
def test_terminated_stream_closes_provider_in_its_own_context(monkeypatch, termination):
    """Close and error cleanup retain stream identity and release the caller context."""
    orchestrator, catalog = _orchestrator()
    closed_efforts = []
    closed_policies = []
    starting_policy = orchestrator.policy

    def stream_chat(agent, messages, *, effort_profile):
        """Expose the context used when the provider iterator is finalized."""
        try:
            yield effort_profile.reasoning_effort
            raise RuntimeError("stream fixture interruption")
        finally:
            closed_efforts.append(orchestrator._role_effort_profile("worker").reasoning_effort)
            closed_policies.append(orchestrator.policy)

    monkeypatch.setattr(orchestrator.client, "stream_chat", stream_chat)
    stream = orchestrator.stream_route([{"role": "user", "content": "terminated fixture"}])
    try:
        assert next(stream) == "medium"
        _change_effort(catalog)
        orchestrator.policy = replace(starting_policy, route_p95_seconds=9)
        if termination == "close":
            stream.close()
        else:
            with pytest.raises(RuntimeError, match="stream fixture interruption"):
                next(stream)
        assert closed_efforts == ["medium"]
        assert closed_policies == [starting_policy]
        assert orchestrator.policy.route_p95_seconds == 9
        assert orchestrator._role_effort_profile("worker").reasoning_effort == "high"
    finally:
        stream.close()
        orchestrator.close()


@pytest.mark.parametrize("entry_point", ["complete", "bypass", "route_once", "conduct", "batch_route", "stream_route", "provider_workflow"])
def test_malformed_catalog_fails_before_any_provider_execution(monkeypatch, entry_point):
    """Every execution boundary validates an operator update before making calls."""
    orchestrator, catalog = _orchestrator()
    catalog.pop("judge")
    provider_calls = []

    def forbidden_call(*args, **kwargs):
        """Fail the test if execution is attempted before catalog validation."""
        provider_calls.append(True)
        raise AssertionError("provider called with an invalid catalog")

    for method in ("chat", "stream_chat", "batch_chat", "proxy_send"):
        monkeypatch.setattr(orchestrator.client, method, forbidden_call)
    messages = [{"role": "user", "content": "invalid catalog fixture"}]
    try:
        with pytest.raises(EffortProfileError, match="catalog must bind exactly"):
            if entry_point == "batch_route":
                orchestrator.batch_route(["invalid catalog fixture"])
            elif entry_point == "stream_route":
                list(orchestrator.stream_route(messages))
            elif entry_point == "bypass":
                orchestrator.complete(messages, mode="route", bypass_cache=True)
            elif entry_point == "provider_workflow":
                orchestrator.proxy_completion(
                    {"model": "mock", "input": "invalid catalog fixture"},
                    endpoint="responses", single_agent=False,
                )
            else:
                getattr(orchestrator, entry_point)(messages)
        assert not provider_calls
    finally:
        orchestrator.close()


def test_no_catalog_request_does_not_adopt_a_late_catalog(monkeypatch):
    """Opting in during a call affects the next request, not the active default path."""
    orchestrator, catalog = _orchestrator()
    orchestrator.role_effort_catalog = None
    received_efforts = []

    def chat(agent, messages, **kwargs):
        """Install the operator catalog after the default request has already started."""
        received_efforts.append(kwargs.get("effort_profile"))
        orchestrator.role_effort_catalog = catalog
        return "fixture answer"

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    messages = [{"role": "user", "content": "late opt-in fixture"}]
    try:
        first = orchestrator.complete(messages, mode="route")
        second = orchestrator.complete(messages, mode="route")
        assert received_efforts[0] is None
        assert "reasoning_effort_snapshot" not in first
        assert received_efforts[1].reasoning_effort == "medium"
        assert second["reasoning_effort_snapshot"]["snapshot_hash"] == snapshot_role_effort_catalog(catalog).snapshot_hash
    finally:
        orchestrator.close()


@pytest.mark.parametrize("mode", ["route", "conduct"])
def test_catalog_is_validated_once_per_completion(monkeypatch, mode):
    """Reuse validation across key construction, nested execution, identity, and records."""
    orchestrator, _unused_catalog = _orchestrator(cache_ttl=60)
    original = runtime_module.snapshot_role_effort_catalog
    calls = []

    def counted_snapshot(value):
        """Count real catalog validations without substituting their output."""
        calls.append(True)
        orchestrator.policy = replace(orchestrator.policy, route_p95_seconds=9)
        return original(value)

    monkeypatch.setattr(runtime_module, "snapshot_role_effort_catalog", counted_snapshot)
    try:
        result = orchestrator.complete([{"role": "user", "content": "validation count fixture"}], mode=mode)
        assert len(calls) == 1
        assert result["policy_snapshot"]["route_p95_seconds"] == 2.5
        assert orchestrator.policy.route_p95_seconds == 9
    finally:
        orchestrator.close()


def test_provider_retry_keeps_the_original_effort_profile(monkeypatch):
    """A retryable transport failure does not switch the active request's effort."""
    orchestrator, catalog = _orchestrator(tool_retry_attempts=1, tool_retry_backoff_seconds=0)
    expected_hash = snapshot_role_effort_catalog(catalog).snapshot_hash
    received_efforts = []
    received_policies = []
    starting_policy = orchestrator.policy

    def chat(agent, messages, *, effort_profile):
        """Change the catalog after the initial attempt, then succeed on retry."""
        received_efforts.append(effort_profile.reasoning_effort)
        received_policies.append(orchestrator.policy)
        if len(received_efforts) == 1:
            _change_effort(catalog)
            orchestrator.policy = replace(starting_policy, route_p95_seconds=9)
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="api_error",
                message="retry fixture failure",
                client_status=502,
                provider_status=503,
                retryable=True,
            )
        return "retried fixture answer"

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    try:
        result = orchestrator.complete([{"role": "user", "content": "retry fixture"}], mode="route")
        assert received_efforts == ["medium", "medium"]
        assert received_policies == [starting_policy, starting_policy]
        assert result["policy_snapshot"] == starting_policy.as_dict()
        assert orchestrator.policy.route_p95_seconds == 9
        assert result["reasoning_effort_snapshot"]["snapshot_hash"] == expected_hash
    finally:
        orchestrator.close()


def test_nested_orchestrators_do_not_inherit_each_others_effort(monkeypatch):
    """Nested execution on another instance restores its caller's distinct revision."""
    orchestrator, catalog = _orchestrator()
    other, other_catalog = _orchestrator()
    _change_effort(other_catalog, "low")
    starting_policy = orchestrator.policy
    other.policy = replace(other.policy, route_p95_seconds=7)
    expected_hash = snapshot_role_effort_catalog(catalog).snapshot_hash
    nested_results = []

    def other_chat(agent, messages, *, effort_profile):
        """Return the nested instance's own declared effort."""
        return effort_profile.reasoning_effort

    def chat(agent, messages, *, effort_profile):
        """Execute a second gateway while retaining the outer request's snapshot."""
        _change_effort(catalog)
        orchestrator.policy = replace(starting_policy, route_p95_seconds=9)
        nested_results.append(other.complete(messages, mode="route"))
        assert orchestrator._role_effort_profile("worker").reasoning_effort == "medium"
        assert orchestrator.policy == starting_policy
        return effort_profile.reasoning_effort

    monkeypatch.setattr(orchestrator.client, "chat", chat)
    monkeypatch.setattr(other.client, "chat", other_chat)
    try:
        result = orchestrator.complete([{"role": "user", "content": "nested fixture"}], mode="route")
        assert result["answer"] == "medium"
        assert result["policy_snapshot"] == starting_policy.as_dict()
        assert nested_results[0]["policy_snapshot"]["route_p95_seconds"] == 7
        assert orchestrator.policy.route_p95_seconds == 9
        assert result["reasoning_effort_snapshot"]["snapshot_hash"] == expected_hash
        assert nested_results[0]["answer"] == "low"
        assert nested_results[0]["reasoning_effort_snapshot"]["snapshot_hash"] == snapshot_role_effort_catalog(other_catalog).snapshot_hash
        assert orchestrator._role_effort_profile("unknown_role") is None
    finally:
        other.close()
        orchestrator.close()
