"""ZDR follow-up: no persistence sink may retain prompt/response content.

Covers the residual gap flagged in
``docs/security/zdr-enforcement-audit-20260917.md`` section 3.7: workflow-run
traces (in-memory and, when a durable ``--state-db`` is configured, sqlite)
must never carry raw prompt/answer/output text for a ``zdr_only`` request --
success, failure, or pending-verification alike. Only non-content metadata
(content hash, byte size, model/provider ids, timings, outcome codes) may
survive at the sink boundary.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import _zdr_content_placeholder


def _zdr_capable_orchestrator(**kwargs) -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(
                "mock_zdr_worker",
                "mock-zdr-model",
                base_url="mock://worker",
                provider_name="mock",
                tags=("reasoning", "writing", "privacy:zdr"),
            )
        ],
        **kwargs,
    )


def _assert_no_content_leak(blob: str, *needles: str) -> None:
    for needle in needles:
        assert needle not in blob, f"raw content {needle!r} leaked into persisted state"


def test_zdr_content_placeholder_carries_only_metadata() -> None:
    placeholder = _zdr_content_placeholder("the secret private-repo prompt")
    assert placeholder["zdr_redacted"] is True
    assert placeholder["byte_size"] == len("the secret private-repo prompt".encode())
    assert placeholder["sha256"] == hashlib.sha256(
        "the secret private-repo prompt".encode()
    ).hexdigest()
    assert "secret" not in json.dumps(placeholder)


def test_zdr_only_run_persists_no_content_in_memory() -> None:
    """The in-memory workflow-run table must be content-free under zdr_only."""
    orchestrator = _zdr_capable_orchestrator()
    prompt = "private repository research prompt: patient cohort details"

    with orchestrator.request_policy(zdr_only=True):
        result = orchestrator.run(
            [{"role": "user", "content": prompt}], mode="route"
        )

    # The live response to the requester itself is unaffected.
    assert result["prompt_text"] == prompt
    assert isinstance(result["answer"], str)

    stored = orchestrator._workflow_runs[result["workflow_run_id"]]
    blob = json.dumps(stored)
    assert stored["prompt_text"]["zdr_redacted"] is True
    for step in stored["trace"]:
        assert step["output"]["zdr_redacted"] is True
    _assert_no_content_leak(blob, prompt, result["answer"])


def test_non_zdr_run_still_persists_content() -> None:
    """Control: ordinary requests keep full content (no behavior regression)."""
    orchestrator = _zdr_capable_orchestrator()
    prompt = "an ordinary, non-private prompt"

    result = orchestrator.run([{"role": "user", "content": prompt}], mode="route")

    stored = orchestrator._workflow_runs[result["workflow_run_id"]]
    assert stored["prompt_text"] == prompt
    assert stored["answer"] == result["answer"]


def test_zdr_only_run_persists_no_content_to_state_db() -> None:
    """The durable sqlite state-db must be content-free under zdr_only."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "state.sqlite3")
        orchestrator = _zdr_capable_orchestrator(state_db=db_path)
        prompt = "private repository research prompt: genomic sample ids"
        try:
            with orchestrator.request_policy(zdr_only=True):
                result = orchestrator.run(
                    [{"role": "user", "content": prompt}], mode="route"
                )
        finally:
            orchestrator.close()

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT payload FROM orchestration_records WHERE kind = 'workflow_run'"
            ).fetchall()
        finally:
            conn.close()

        assert rows
        for (payload,) in rows:
            _assert_no_content_leak(payload, prompt, result["answer"])
            record = json.loads(payload)
            assert record["prompt_text"]["zdr_redacted"] is True


def test_zdr_only_failed_workflow_run_persists_no_content() -> None:
    """Fail-closed redaction applies to failure/retry records too, not only success.

    Exercises ``_replace_workflow_run`` directly with the same record shape the
    conduct failure path builds (a truthy ``failure`` code alongside partial
    prompt/answer/trace content), so a future failure/retry code path cannot
    silently bypass the sink boundary the success path already covers above.
    """
    orchestrator = _zdr_capable_orchestrator()
    prompt = "private repository prompt that triggered a provider failure"
    partial_answer = "partial answer captured before the failure"

    with orchestrator.request_policy(zdr_only=True):
        record = {
            "workflow_run_id": "run_failure_test",
            "created_at": 0,
            "mode": "conduct",
            "policy_mode": "conduct",
            "prompt_text": prompt,
            "answer": partial_answer,
            "cache_status": "bypass",
            "trace": [
                {
                    "id": "step_1",
                    "role": "worker",
                    "agent_id": "mock_zdr_worker",
                    "output": partial_answer,
                }
            ],
            "policy_snapshot": orchestrator.policy.as_dict(),
            "verification": None,
            "failure": {"code": "provider_error"},
        }
        orchestrator._replace_workflow_run(record)

    stored = orchestrator._workflow_runs["run_failure_test"]
    blob = json.dumps(stored)
    assert stored["failure"] == {"code": "provider_error"}
    _assert_no_content_leak(blob, prompt, partial_answer)


def test_zdr_only_evaluation_run_persists_no_content() -> None:
    """run_evaluation's stored results must not carry raw answers under zdr_only."""
    orchestrator = _zdr_capable_orchestrator()

    with orchestrator.request_policy(zdr_only=True):
        evaluation = orchestrator.run_evaluation(["private prompt one", "private prompt two"])

    # The caller's own return value keeps real answers (needed by the caller
    # of this diagnostic path); only the persisted copy is redacted.
    assert all(isinstance(r["answer"], str) for r in evaluation["results"])

    stored = orchestrator._evaluation_runs[evaluation["evaluation_run_id"]]
    blob = json.dumps(stored)
    for result in stored["results"]:
        assert result["answer"]["zdr_redacted"] is True
    for real_result in evaluation["results"]:
        if real_result["answer"]:
            assert real_result["answer"] not in blob


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
