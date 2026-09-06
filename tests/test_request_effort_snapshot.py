"""Request-boundary regressions for declared effort, identity, and answer records."""

from dataclasses import replace

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator, default_role_effort_catalog
from contextual_orchestrator.reasoning_effort_profile import snapshot_role_effort_catalog


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
