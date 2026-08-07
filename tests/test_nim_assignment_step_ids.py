"""Contracts for deterministic benchmark model-assignment step identities."""

from __future__ import annotations

import json

import pytest

from contextual_orchestrator import nim_csv_evidence as csv_evidence


def _assignment(step_id: object, model_id: str = "vendor/model-a") -> dict[str, object]:
    """Build one assignment fixture with a configurable raw trace identifier."""
    return {
        "step_id": step_id,
        "role": "worker",
        "agent_id": "agent_one",
        "model_id": model_id,
    }


def test_empty_trace_step_ids_receive_stable_positional_identifiers() -> None:
    """Route traces without plan IDs must remain complete, unique CSV evidence."""
    serialized = csv_evidence._models_used_json(
        [_assignment(""), _assignment("   ", "vendor/model-b")]
    )

    assert json.loads(serialized) == [
        {
            "step_id": "trace_step_0001",
            "role": "worker",
            "agent_id": "agent_one",
            "model_id": "vendor/model-a",
        },
        {
            "step_id": "trace_step_0002",
            "role": "worker",
            "agent_id": "agent_one",
            "model_id": "vendor/model-b",
        },
    ]


def test_existing_trace_step_id_is_preserved_exactly() -> None:
    """A real non-empty trace identifier must not be rewritten by publication."""
    serialized = csv_evidence._models_used_json([_assignment("planner_step")])
    assert json.loads(serialized)[0]["step_id"] == "planner_step"


def test_duplicate_non_empty_trace_step_ids_fail_closed() -> None:
    """Two assignments may not claim the same explicit workflow-step identity."""
    with pytest.raises(csv_evidence.CsvEvidenceError, match="duplicate step_id"):
        csv_evidence._models_used_json(
            [_assignment("same_step"), _assignment("same_step", "vendor/model-b")]
        )


def test_missing_or_non_string_trace_step_id_is_not_synthesized() -> None:
    """Only a present string known to be the empty route sentinel is canonicalized."""
    with pytest.raises(csv_evidence.CsvEvidenceError, match="step_id"):
        csv_evidence._models_used_json([_assignment(None)])
