"""Blocked-side coverage for commercial readiness reports.

Every commercial report degrades honestly when repository evidence
disappears. This module simulates a stripped checkout by hiding all
documentation and focused-test files, then exercises each report so the
concrete-blocker branches stay covered alongside their ready-with-warnings
counterparts.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


TARGET_CONTRACT_VALUE_KRW = 2_000_000_000


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security")),
        ]
    )


@contextmanager
def hidden_repository_files() -> Iterator[None]:
    """Make every documentation/test artifact look missing to has_file()."""

    def always_missing(self: Path) -> bool:
        del self
        return False

    with patch.object(Path, "is_file", always_missing):
        yield


REPORT_NAMES = [
    "commercial_evidence_export_report",
    "commercial_acceptance_check_report",
    "commercial_release_candidate_report",
    "commercial_gap_register_report",
    "commercial_procurement_readiness_report",
    "commercial_contract_readiness_report",
    "commercial_onboarding_readiness_report",
    "commercial_operations_readiness_report",
    "commercial_security_attestation_report",
    "commercial_value_readiness_report",
    "commercial_close_readiness_report",
    "commercial_go_to_market_readiness_report",
    "commercial_launch_readiness_report",
    "commercial_completion_scorecard_report",
    "commercial_buyer_acceptance_workflow_report",
    "buyer_evidence_manifest_report",
    "buyer_handoff_bundle_report",
    "saleability_decision_report",
]


@pytest.mark.parametrize("report_name", REPORT_NAMES)
def test_reports_degrade_to_blocked_without_repository_evidence(
    report_name: str,
) -> None:
    """With no repo artifacts present, no report may claim full readiness."""
    orchestrator = build()
    with hidden_repository_files():
        report = getattr(orchestrator, report_name)(
            target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW
        )
    assert isinstance(report, dict)
    status_keys = [
        key
        for key in report
        if key.endswith("_status")
        or key in {"decision_label", "recommendation_status"}
    ]
    assert status_keys, f"{report_name} exposes no status field"
    joined = " ".join(str(report[key]) for key in status_keys)
    assert "blocked" in joined or "not_ready" in joined or "do_not_recommend" in joined, (
        f"{report_name} claimed readiness without repository evidence: {joined}"
    )


def test_readiness_and_scorecards_surface_concrete_blockers() -> None:
    """The top-level readiness chain names the missing-evidence blockers."""
    orchestrator = build()
    with hidden_repository_files():
        readiness = orchestrator.commercial_readiness_report(
            target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW
        )
        completion = orchestrator.commercial_completion_scorecard_report(
            target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW
        )

    assert readiness["sales_readiness"]["readiness_summary"]["fail"] > 0
    assert completion["completion_status"].endswith("blocked")
    # The blocker identifiers inherited from saleability must be hashable
    # strings (regression: unhashable dicts crashed dict.fromkeys dedupe).
    assert all(isinstance(b, str) for b in completion["concrete_blockers"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
