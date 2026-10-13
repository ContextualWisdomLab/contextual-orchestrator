"""Observed delivered-correct comparisons keep every declared request pair."""

from __future__ import annotations

import pytest

from contextual_orchestrator.observed_quality import (
    PairedQualityOutcome,
    paired_delivered_correct_interval,
)


def _outcome(
    index: int, candidate: bool, baseline: bool, *, failed: bool = False
) -> PairedQualityOutcome:
    return PairedQualityOutcome(
        task_id=f"task-{index}",
        candidate_delivered=not failed,
        candidate_correct=candidate if not failed else None,
        candidate_judgment_ref=f"human-c-{index}" if not failed else None,
        baseline_delivered=not failed,
        baseline_correct=baseline if not failed else None,
        baseline_judgment_ref=f"human-b-{index}" if not failed else None,
    )


def test_newcombe_paired_score_matches_published_manual_example_and_counts_failures() -> (
    None
):
    # NCSS PASS manual example 2 (Newcombe 1998, method 10):
    # f11=20, f10=12, f01=2, f00=16; n=50; 95% CI 0.0562..0.3292.
    rows = (
        [_outcome(i, True, True) for i in range(20)]
        + [_outcome(i, True, False) for i in range(20, 32)]
        + [_outcome(i, False, True) for i in range(32, 34)]
        + [_outcome(i, False, False, failed=i < 39) for i in range(34, 50)]
    )
    report = paired_delivered_correct_interval(
        rows,
        expected_task_ids={row.task_id for row in rows},
        confidence_level=0.95,
    )

    assert report["pair_count"] == 50
    assert report["candidate_delivered_correct_count"] == 32
    assert report["baseline_delivered_correct_count"] == 22
    assert report["candidate_delivery_failure_count"] == 5
    assert report["baseline_delivery_failure_count"] == 5
    assert report["candidate_rate"] == pytest.approx(0.64)
    assert report["baseline_rate"] == pytest.approx(0.44)
    assert report["difference"] == pytest.approx(0.2)
    assert report["ci_low"] == pytest.approx(0.0562, abs=0.0001)
    assert report["ci_high"] == pytest.approx(0.3292, abs=0.0001)
    assert report["method"] == "newcombe_paired_score_10"


def test_observed_quality_rejects_missing_pairs_and_unjudged_delivery() -> None:
    row = _outcome(1, True, False)
    with pytest.raises(ValueError, match="complete declared task set"):
        paired_delivered_correct_interval(
            [row], expected_task_ids={"task-1", "task-2"}, confidence_level=0.95
        )
    with pytest.raises(ValueError, match="duplicate"):
        paired_delivered_correct_interval(
            [row, row], expected_task_ids={"task-1"}, confidence_level=0.95
        )
    with pytest.raises(ValueError, match="independent judgment"):
        paired_delivered_correct_interval(
            [
                PairedQualityOutcome(
                    "task-1", True, None, None, True, False, "human-b-1"
                )
            ],
            expected_task_ids={"task-1"},
            confidence_level=0.95,
        )


def test_all_failed_deliveries_remain_in_the_denominator() -> None:
    rows = [_outcome(i, False, False, failed=True) for i in range(3)]
    report = paired_delivered_correct_interval(
        rows,
        expected_task_ids={row.task_id for row in rows},
        confidence_level=0.95,
    )
    assert report["pair_count"] == 3
    assert report["candidate_delivery_failure_count"] == 3
    assert report["baseline_delivery_failure_count"] == 3
    assert report["candidate_rate"] == report["baseline_rate"] == 0
    assert report["ci_low"] <= 0 <= report["ci_high"]
