"""Paired, independently adjudicated delivered-correct pilot measurements."""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from statistics import NormalDist


@dataclass(frozen=True)
class PairedQualityOutcome:
    """One declared task observed under both policies with judgment references."""

    task_id: str
    candidate_delivered: bool
    candidate_correct: bool | None
    candidate_judgment_ref: str | None
    baseline_delivered: bool
    baseline_correct: bool | None
    baseline_judgment_ref: str | None


def _delivered_correct(
    delivered: bool, correct: bool | None, judgment_ref: str | None
) -> int:
    if type(delivered) is not bool:
        raise ValueError("delivery must be a boolean")
    if not delivered:
        if correct is not None or judgment_ref is not None:
            raise ValueError("failed delivery cannot carry a judgment")
        return 0
    if (
        type(correct) is not bool
        or not isinstance(judgment_ref, str)
        or not judgment_ref.strip()
    ):
        raise ValueError(
            "delivered answers require an independent judgment reference and Boolean result"
        )
    return int(correct)


def _wilson_interval(successes: int, count: int, z: float) -> tuple[float, float]:
    proportion = successes / count
    scale = 1 + z * z / count
    center = (proportion + z * z / (2 * count)) / scale
    half_width = (
        z
        * math.sqrt(proportion * (1 - proportion) / count + z * z / (4 * count * count))
        / scale
    )
    return center - half_width, center + half_width


def paired_delivered_correct_interval(
    observations: Iterable[PairedQualityOutcome],
    *,
    expected_task_ids: Collection[str],
    confidence_level: float,
) -> dict[str, float | int | str | dict[str, int]]:
    """Return Newcombe method 10's interval for candidate minus baseline.

    The caller must predeclare the complete accepted-task set and independently
    verify the referenced human judgments. This numerical function cannot prove
    adjudicator identity, blinding, or sampling design.
    """
    expected = list(expected_task_ids)
    if (
        not expected
        or any(not isinstance(task_id, str) or not task_id for task_id in expected)
        or len(set(expected)) != len(expected)
    ):
        raise ValueError("expected task IDs must be unique nonempty strings")
    if (
        type(confidence_level) not in (int, float)
        or not math.isfinite(confidence_level)
        or not 0 < confidence_level < 1
    ):
        raise ValueError("confidence level must be finite and between zero and one")
    rows = list(observations)
    if any(not isinstance(row, PairedQualityOutcome) for row in rows):
        raise ValueError("all observations must be paired quality outcomes")
    task_ids = [row.task_id for row in rows]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("duplicate task observation")
    if set(task_ids) != set(expected):
        raise ValueError("observations must match the complete declared task set")

    f11 = f10 = f01 = f00 = candidate_failures = baseline_failures = 0
    for row in rows:
        candidate = _delivered_correct(
            row.candidate_delivered, row.candidate_correct, row.candidate_judgment_ref
        )
        baseline = _delivered_correct(
            row.baseline_delivered, row.baseline_correct, row.baseline_judgment_ref
        )
        candidate_failures += not row.candidate_delivered
        baseline_failures += not row.baseline_delivered
        if candidate and baseline:
            f11 += 1
        elif candidate:
            f10 += 1
        elif baseline:
            f01 += 1
        else:
            f00 += 1

    count = len(rows)
    z = NormalDist().inv_cdf((1 + confidence_level) / 2)
    candidate_rate = (f11 + f10) / count
    baseline_rate = (f11 + f01) / count
    candidate_low, candidate_high = _wilson_interval(f11 + f10, count, z)
    baseline_low, baseline_high = _wilson_interval(f11 + f01, count, z)
    margin_product = (f11 + f10) * (f01 + f00) * (f11 + f01) * (f10 + f00)
    cross_product = f11 * f00 - f10 * f01
    corrected = (
        cross_product - count / 2
        if cross_product > count / 2
        else min(cross_product, 0)
    )
    correlation = corrected / math.sqrt(margin_product) if margin_product else 0.0
    difference = candidate_rate - baseline_rate
    candidate_lower_width = candidate_rate - candidate_low
    baseline_upper_width = baseline_high - baseline_rate
    baseline_lower_width = baseline_rate - baseline_low
    candidate_upper_width = candidate_high - candidate_rate
    lower_radius = math.sqrt(
        max(
            0.0,
            candidate_lower_width**2
            - 2 * correlation * candidate_lower_width * baseline_upper_width
            + baseline_upper_width**2,
        )
    )
    upper_radius = math.sqrt(
        max(
            0.0,
            baseline_lower_width**2
            - 2 * correlation * baseline_lower_width * candidate_upper_width
            + candidate_upper_width**2,
        )
    )
    return {
        "pair_count": count,
        "candidate_delivered_correct_count": f11 + f10,
        "baseline_delivered_correct_count": f11 + f01,
        "candidate_delivery_failure_count": candidate_failures,
        "baseline_delivery_failure_count": baseline_failures,
        "candidate_rate": candidate_rate,
        "baseline_rate": baseline_rate,
        "difference": difference,
        "ci_low": max(-1.0, difference - lower_radius),
        "ci_high": min(1.0, difference + upper_radius),
        "confidence_level": confidence_level,
        "method": "newcombe_paired_score_10",
        "pair_counts": {"f11": f11, "f10": f10, "f01": f01, "f00": f00},
    }
