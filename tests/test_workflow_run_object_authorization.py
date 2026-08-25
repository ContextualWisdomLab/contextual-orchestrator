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
    evaluation = orchestrator.run_evaluation(["one"], owner_id="owner_a")
    assert orchestrator.get_evaluation_run(evaluation["evaluation_run_id"], owner_id="owner_a") == evaluation

    with pytest.raises(KeyError):
        orchestrator.get_workflow_run(run_id, owner_id="owner_b")
    with pytest.raises(KeyError):
        orchestrator.get_access_report(run_id, owner_id="owner_b")
    with pytest.raises(KeyError):
        orchestrator.get_evaluation_run(evaluation["evaluation_run_id"], owner_id="owner_b")
    assert orchestrator.list_recent_runs(owner_id="owner_b") == []
    assert orchestrator.count_workflow_runs(owner_id="owner_b") == 0


def test_evaluation_runs_carry_owner_boundary() -> None:
    """Keep replay results within the principal that created them."""
    orchestrator = _orchestrator()
    evaluation = orchestrator.run_evaluation(["one"], owner_id="owner_a")
    assert evaluation["owner_id"] == "owner_a"
    assert evaluation["results"][0]["workflow_run_id"] in evaluation["workflow_run_ids"]


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
    """Hide record owners without altering similarly named provider output."""
    payload = _response_payload(
        {
            "owner_id": "owner_a",
            "items": [{"owner_id": "owner_a", "value": "visible"}],
            "trace": [{"output": {"owner_id": "provider-authored"}}],
        },
        include_trace=True,
    )
    assert payload == {
        "items": [{"value": "visible"}],
        "trace": [{"output": {"owner_id": "provider-authored"}}],
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
