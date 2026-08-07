"""Tests for fallback value validation and plan ordering."""

from __future__ import annotations

import pytest

from contextual_orchestrator.model_fallback import (
    CandidateValidationError,
    CostTier,
    FallbackCandidate,
    FallbackContext,
    NoEligibleCandidateError,
    SkippedCandidate,
    build_fallback_plan,
)
from tests.fallback_test_support import candidate


def test_plan_places_all_free_candidates_before_paid_candidates() -> None:
    """Paid priority cannot jump ahead of an eligible free candidate."""
    plan = build_fallback_plan(
        [
            candidate(
                "paid-fast", "paid/fast", cost_tier=CostTier.PAID, priority=0
            ),
            candidate("free-second", "free/second", priority=20),
            candidate("free-first", "free/first", priority=10),
            candidate(
                "paid-second",
                "paid/second",
                cost_tier=CostTier.PAID,
                priority=5,
            ),
        ]
    )

    assert plan.candidate_ids == (
        "free-first",
        "free-second",
        "paid-fast",
        "paid-second",
    )
    assert tuple(item.model for item in plan.free_candidates) == (
        "free/first",
        "free/second",
    )
    assert tuple(item.model for item in plan.paid_candidates) == (
        "paid/fast",
        "paid/second",
    )
    assert [item["candidate_id"] for item in plan.to_public_dict()["candidates"]] == [
        "free-first",
        "free-second",
        "paid-fast",
        "paid-second",
    ]


def test_plan_is_stable_for_equal_cost_and_priority() -> None:
    """Declaration order is the deterministic final tie-breaker."""
    plan = build_fallback_plan(
        [candidate("free-a", "free/a"), candidate("free-b", "free/b")]
    )
    assert plan.candidate_ids == ("free-a", "free-b")


def test_plan_filters_by_credentials_visibility_and_capabilities() -> None:
    """Eligibility is evaluated without exposing credential values."""
    plan = build_fallback_plan(
        [
            candidate(
                "eligible",
                "free/eligible",
                credentials=("FREE_API_KEY",),
                visibilities=frozenset({"public"}),
                capabilities=frozenset({"text", "structured_output"}),
            ),
            candidate(
                "private-only",
                "free/private",
                visibilities=frozenset({"private"}),
            ),
            candidate(
                "missing-key",
                "free/missing",
                credentials=("OTHER_API_KEY",),
            ),
            candidate(
                "missing-capability",
                "free/no-json",
                capabilities=frozenset({"text"}),
            ),
        ],
        context=FallbackContext(
            repository_visibility="public",
            available_credentials=frozenset({"FREE_API_KEY"}),
            required_capabilities=frozenset({"structured_output"}),
        ),
    )
    assert plan.candidate_ids == ("eligible",)
    assert tuple((item.candidate_id, item.reason) for item in plan.skipped) == (
        ("private-only", "repository_visibility"),
        ("missing-key", "missing_credentials:OTHER_API_KEY"),
        ("missing-capability", "missing_capabilities:structured_output"),
    )


def test_plan_can_disable_paid_fallbacks() -> None:
    """A caller can prohibit paid candidates while retaining free fallback."""
    plan = build_fallback_plan(
        [
            candidate("paid", "paid/model", cost_tier=CostTier.PAID),
            candidate("free", "free/model"),
        ],
        context=FallbackContext(allow_paid=False),
    )
    assert plan.candidate_ids == ("free",)
    assert plan.skipped[0].reason == "paid_candidates_disabled"


def test_plan_rejects_duplicates_and_empty_or_untyped_inputs() -> None:
    """A pool cannot repeat a logical target or silently accept no target."""
    with pytest.raises(CandidateValidationError, match="duplicate candidate_id"):
        build_fallback_plan(
            [candidate("same", "model/a"), candidate("same", "model/b")]
        )
    with pytest.raises(CandidateValidationError, match="duplicate provider/model"):
        build_fallback_plan(
            [candidate("first", "model/a"), candidate("second", "model/a")]
        )
    with pytest.raises(NoEligibleCandidateError, match="candidate list was empty"):
        build_fallback_plan([])
    with pytest.raises(CandidateValidationError, match="FallbackCandidate"):
        build_fallback_plan([object()])  # type: ignore[list-item]


def test_plan_raises_when_every_candidate_is_ineligible() -> None:
    """The planner never turns an empty eligible pool into success."""
    with pytest.raises(NoEligibleCandidateError, match="MISSING_KEY"):
        build_fallback_plan(
            [candidate("needs-key", "free/model", credentials=("MISSING_KEY",))]
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("candidate_id", "bad id", "candidate_id"),
        ("provider", "Provider/Bad", "provider"),
        ("model", "bad model", "model"),
        ("cost_tier", "free", "cost_tier"),
        ("priority", -1, "priority"),
        ("priority", True, "priority"),
        ("required_credentials", ("bad-key",), "credential"),
        ("required_credentials", ["API_KEY"], "tuple"),
        ("repository_visibilities", frozenset({"secret"}), "visibility"),
        ("capabilities", frozenset({"Structured Output"}), "capability"),
    ],
)
def test_candidate_validation_rejects_unsafe_values(
    field: str, value: object, message: str
) -> None:
    """Workflow control fields are strict and shell-safe."""
    values: dict[str, object] = {
        "candidate_id": "candidate-one",
        "provider": "provider",
        "model": "model/one",
        "cost_tier": CostTier.FREE,
        "priority": 1,
        "required_credentials": (),
        "repository_visibilities": frozenset({"public"}),
        "capabilities": frozenset({"text"}),
    }
    values[field] = value
    with pytest.raises(CandidateValidationError, match=message):
        FallbackCandidate(**values)  # type: ignore[arg-type]


def test_context_and_collection_types_fail_closed() -> None:
    """Truthy strings and mutable control collections cannot bypass policy."""
    with pytest.raises(CandidateValidationError, match="visibility"):
        FallbackContext(repository_visibility="secret")
    with pytest.raises(CandidateValidationError, match="visibility"):
        FallbackContext(repository_visibility=[])  # type: ignore[arg-type]
    with pytest.raises(CandidateValidationError, match="frozenset"):
        FallbackContext(available_credentials=["API_KEY"])  # type: ignore[arg-type]
    with pytest.raises(CandidateValidationError, match="credential"):
        FallbackContext(available_credentials=frozenset({"bad-key"}))
    with pytest.raises(CandidateValidationError, match="capability"):
        FallbackContext(required_capabilities=frozenset({"bad capability"}))
    with pytest.raises(CandidateValidationError, match="allow_paid"):
        FallbackContext(allow_paid="false")  # type: ignore[arg-type]
    with pytest.raises(CandidateValidationError, match="sequence"):
        candidate(
            "candidate", "model/one", credentials="API_KEY"  # type: ignore[arg-type]
        )
    with pytest.raises(CandidateValidationError, match="non-empty"):
        candidate(
            "candidate", "model/one", visibilities=frozenset()
        )
    with pytest.raises(CandidateValidationError, match="non-empty"):
        candidate(
            "candidate", "model/one", visibilities={"public"}  # type: ignore[arg-type]
        )
    with pytest.raises(CandidateValidationError, match="frozenset"):
        candidate(
            "candidate", "model/one", capabilities={"text"}  # type: ignore[arg-type]
        )


def test_public_records_never_require_secret_values() -> None:
    """Candidate and skip records expose only names and public reasons."""
    item = candidate(
        "free", "free/model", credentials=("FREE_API_KEY",)
    ).to_public_dict()
    assert item["required_credentials"] == ["FREE_API_KEY"]
    skipped = SkippedCandidate(
        "candidate", "missing_credentials:FREE_API_KEY"
    )
    assert skipped.to_public_dict() == {
        "candidate_id": "candidate",
        "reason": "missing_credentials:FREE_API_KEY",
    }
