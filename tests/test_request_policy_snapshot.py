"""Execution-policy regressions for judging, request identity, and saved evidence."""

from dataclasses import replace
from hashlib import sha256
import json

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


def _policy_gateway(**cache_options):
    """Use a local worker with judging disabled until the operator changes policy."""
    gateway = TaskOrchestrator(
        [ModelAgent("policy_worker", "mock", tags=("reasoning", "writing"))],
        **cache_options,
    )
    gateway.policy = replace(gateway.policy, realtime_judge=False)
    return gateway


def _accept_judgment(_task_text, verification, **_request_options):
    """Return a deterministic judgment without contacting an external provider."""
    return {**verification, "accepted": True, "reason": "unit judge executed", "judge": "model"}


@pytest.mark.parametrize(
    ("entry_point", "request_options"),
    [
        ("complete", {"mode": "route"}),
        ("complete", {"mode": "conduct"}),
        ("route_once", {}),
        ("conduct", {}),
        ("run", {"mode": "route"}),
    ],
)
def test_request_retains_starting_policy(monkeypatch, entry_point, request_options):
    """Execution and saved evidence retain one policy while later requests see updates."""
    gateway = _policy_gateway()
    starting_policy = gateway.policy
    policy_hash = sha256(json.dumps(
        starting_policy.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
    seen_policies = []

    def worker_reply(_agent, _messages, **_request_options):
        """Publish a later policy while recording which policy this execution sees."""
        seen_policies.append(gateway.policy)
        gateway.policy = replace(starting_policy, realtime_judge=True, verifier_required=False)
        seen_policies.append(gateway.policy)
        return "unit worker answer"

    monkeypatch.setattr(gateway.client, "chat", worker_reply)
    monkeypatch.setattr(gateway, "_model_judge_verification", _accept_judgment)
    try:
        result = getattr(gateway, entry_point)(
            [{"role": "user", "content": "policy revision unit fixture"}], **request_options
        )
        assert seen_policies and all(policy == starting_policy for policy in seen_policies)
        assert result["policy_snapshot"] == starting_policy.as_dict()
        assert all(row["selection_design"]["policy_snapshot_hash"] == policy_hash for row in result["trace"])
        assert gateway.policy.realtime_judge is True
        assert gateway.policy.verifier_required is False
    finally:
        gateway.close()


def test_run_preserves_completed_policy_before_persistence(monkeypatch):
    """A policy update after completion must not relabel the completed answer."""
    gateway = _policy_gateway()
    original_complete = gateway.complete
    completed_results = []

    def complete_then_update(*request_args, **request_options):
        """Update operator policy only after the real completion has returned."""
        result = original_complete(*request_args, **request_options)
        completed_results.append(result)
        gateway.policy = replace(gateway.policy, realtime_judge=True)
        return result

    monkeypatch.setattr(gateway, "complete", complete_then_update)
    try:
        record = gateway.run([{"role": "user", "content": "saved policy unit fixture"}], mode="route")
        assert record["policy_snapshot"]["realtime_judge"] is False
        completed_results[0]["policy_snapshot"]["workflow_steps"].clear()
        assert record["policy_snapshot"]["workflow_steps"]
    finally:
        gateway.close()


def test_interleaved_streams_retain_separate_policies(monkeypatch):
    """Suspended streams retain their own policy and restore the caller between deltas."""
    gateway = _policy_gateway()

    def stream_reply(_agent, _messages, **_request_options):
        """Read effective policy on both sides of a suspension point."""
        yield str(gateway.policy.realtime_judge)
        yield str(gateway.policy.realtime_judge)

    monkeypatch.setattr(gateway.client, "stream_chat", stream_reply)
    monkeypatch.setattr(gateway, "_model_judge_verification", _accept_judgment)
    messages = [{"role": "user", "content": "stream policy unit fixture"}]
    first_stream = gateway.stream_route(messages, workflow_run_id="first_policy_stream")
    second_stream = gateway.stream_route(messages, workflow_run_id="second_policy_stream")
    try:
        assert next(first_stream) == "False"
        gateway.policy = replace(gateway.policy, realtime_judge=True)
        assert next(second_stream) == "True"
        assert list(first_stream) == ["False"]
        assert list(second_stream) == ["True"]
        assert gateway.get_workflow_run("first_policy_stream")["policy_snapshot"]["realtime_judge"] is False
        assert gateway.get_workflow_run("second_policy_stream")["policy_snapshot"]["realtime_judge"] is True
        assert gateway.policy.realtime_judge is True
    finally:
        first_stream.close()
        second_stream.close()
        gateway.close()


def test_batch_records_retain_submission_policy(monkeypatch):
    """Pending and completed rows must describe the policy used by their batch."""
    gateway = _policy_gateway()
    saved_policies = []
    original_replace = gateway._replace_workflow_run

    def batch_reply(_agent, requests, **_request_options):
        """Publish later settings after accepting this batch's worker requests."""
        gateway.policy = replace(gateway.policy, realtime_judge=True)
        return {request_id: {"content": "unit batch answer"} for request_id in requests}

    def save_record(record):
        """Observe both pending and final records without replacing persistence."""
        saved_policies.append(record["policy_snapshot"]["realtime_judge"])
        return original_replace(record)

    monkeypatch.setattr(gateway.client, "batch_chat", batch_reply)
    monkeypatch.setattr(gateway, "_replace_workflow_run", save_record)
    monkeypatch.setattr(gateway, "_model_judge_verification", _accept_judgment)
    try:
        records = gateway.batch_route(["first batch unit fixture", "second batch unit fixture"])
        assert saved_policies == [False, False, False, False]
        assert all(record["policy_snapshot"]["realtime_judge"] is False for record in records)
        records[0]["policy_snapshot"]["workflow_steps"].clear()
        assert records[1]["policy_snapshot"]["workflow_steps"]
        assert gateway.policy.realtime_judge is True
    finally:
        gateway.close()


@pytest.mark.parametrize("policy_change", [
    {"route_p95_seconds": 3.0},
    {"realtime_judge": True},
    {"verifier_required": False},
    {"workflow_planning": "generated"},
    {"max_workflow_steps": 5},
])
def test_cache_identity_tracks_each_changeable_policy_field(policy_change):
    """Every configurable policy field partitions reuse; equal content preserves identity."""
    gateway = _policy_gateway()
    messages = [{"role": "user", "content": "policy cache identity fixture"}]
    try:
        first_key = gateway._cache_key(messages, "route")
        gateway.policy = replace(gateway.policy, **policy_change)
        changed_key = gateway._cache_key(messages, "route")
        assert changed_key != first_key
        gateway.policy = replace(gateway.policy)
        assert gateway._cache_key(messages, "route") == changed_key
    finally:
        gateway.close()


@pytest.mark.parametrize("endpoint", ["responses", "chat/completions"])
def test_provider_shaped_workflow_keeps_policy_through_synthesis(monkeypatch, endpoint):
    """Workflow, final synthesis, and the saved run must retain one request policy."""
    gateway = _policy_gateway()
    seen_policies = []

    def worker_reply(_agent, _messages, **_request_options):
        """Change the later policy during the conducted evidence workflow."""
        gateway.policy = replace(gateway.policy, realtime_judge=True)
        seen_policies.append(gateway.policy.realtime_judge)
        return "unit workflow answer"

    def synthesis_reply(_agent, _endpoint, _payload):
        """Return the provider's public response shape for the final synthesis."""
        seen_policies.append(gateway.policy.realtime_judge)
        return {"output_text": "{}"} if endpoint == "responses" else {
            "choices": [{"message": {"content": "{}"}}]
        }

    monkeypatch.setattr(gateway.client, "chat", worker_reply)
    monkeypatch.setattr(gateway.client, "proxy_send", synthesis_reply)
    monkeypatch.setattr(gateway, "_model_judge_verification", _accept_judgment)
    request_body = {"model": "mock", "response_format": {"type": "json_object"}}
    request_body.update(
        {"input": "provider policy unit fixture"} if endpoint == "responses" else {
            "messages": [{"role": "user", "content": "provider policy unit fixture"}]
        }
    )
    try:
        result = gateway.proxy_completion(request_body, endpoint=endpoint, single_agent=False)
        assert seen_policies and not any(seen_policies)
        record = gateway.get_workflow_run(result["orchestration"]["workflow_run_id"])
        assert record["policy_snapshot"]["realtime_judge"] is False
        assert gateway.policy.realtime_judge is True
    finally:
        gateway.close()
