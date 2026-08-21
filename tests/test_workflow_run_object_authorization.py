"""Regression coverage for owner-bound workflow and access-report reads."""

from __future__ import annotations

from email.message import Message
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    _response_payload,
)


def _orchestrator() -> TaskOrchestrator:
    """Build one deterministic local gateway for ownership tests."""
    return TaskOrchestrator([ModelAgent("general_agent", "mock-generalist")])


def test_workflow_and_access_reads_are_owner_bound() -> None:
    """Do not let one authenticated principal retrieve another principal's run."""
    orchestrator = _orchestrator()
    record = orchestrator.run(
        [{"role": "user", "content": "owner-bound request"}], owner_id="owner_a"
    )
    run_id = record["workflow_run_id"]

    assert orchestrator.get_workflow_run(run_id, owner_id="owner_a") == record
    assert orchestrator.list_recent_runs(owner_id="owner_a") == [record]
    assert orchestrator.count_workflow_runs(owner_id="owner_a") == 1
    assert orchestrator.get_access_report(run_id, owner_id="owner_a")["workflow_run_id"] == run_id

    with pytest.raises(KeyError):
        orchestrator.get_workflow_run(run_id, owner_id="owner_b")
    with pytest.raises(KeyError):
        orchestrator.get_access_report(run_id, owner_id="owner_b")
    assert orchestrator.list_recent_runs(owner_id="owner_b") == []
    assert orchestrator.count_workflow_runs(owner_id="owner_b") == 0


def test_evaluation_runs_carry_owner_boundary() -> None:
    """Keep replay results within the principal that created them."""
    orchestrator = _orchestrator()
    evaluation = orchestrator.run_evaluation(["one"], owner_id="owner_a")
    assert evaluation["owner_id"] == "owner_a"
    assert evaluation["results"][0]["workflow_run_id"] in evaluation["workflow_run_ids"]


def test_audit_events_follow_workflow_and_evaluation_owners() -> None:
    """Resource audit identifiers must not cross an external principal boundary."""
    orchestrator = _orchestrator()
    owner_a_run = orchestrator.run(
        [{"role": "user", "content": "owner a run"}], owner_id="owner_a"
    )
    owner_b_evaluation = orchestrator.run_evaluation(["owner b evaluation"], owner_id="owner_b")
    unowned_run = orchestrator.run([{"role": "user", "content": "legacy unowned run"}])
    orchestrator._audit_events.extend(
        [
            "malformed",
            {"event_detail": []},
            {"event_detail": {"workflow_run_id": []}},
            {"event_detail": {"evaluation_run_id": []}},
        ]
    )

    owner_a_events = repr(orchestrator.list_recent_audit_events(owner_id="owner_a"))
    owner_b_events = repr(orchestrator.list_recent_audit_events(owner_id="owner_b"))

    assert owner_a_run["workflow_run_id"] in owner_a_events
    assert owner_b_evaluation["evaluation_run_id"] not in owner_a_events
    assert unowned_run["workflow_run_id"] not in owner_a_events
    assert owner_a_run["workflow_run_id"] not in owner_b_events
    assert owner_b_evaluation["evaluation_run_id"] in owner_b_events


def test_principal_id_is_a_stable_non_secret_token_digest() -> None:
    """Use a token-derived lookup key without returning or storing the token."""
    headers = Message()
    headers["Authorization"] = "Bearer test-token"
    security = SecurityConfig(auth_token="test-token")
    principal = security.principal_id(headers)
    assert principal == security.principal_id(headers)
    assert principal != "test-token"
    assert len(principal) == 64


def test_public_payload_removes_internal_owner_metadata_recursively() -> None:
    """Keep owner lookup keys out of trace-enabled and list response bodies."""
    payload = _response_payload(
        {"owner_id": "owner_a", "items": [{"owner_id": "owner_a", "value": "visible"}]},
        include_trace=True,
    )
    assert payload == {"items": [{"value": "visible"}]}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
