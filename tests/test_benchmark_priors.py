"""Benchmark-prior derivation: measurement-typed, budget-preserving, monotone."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.benchmark_priors import (
    PRIOR_EVIDENCE_BUDGET,
    measured_quality_probability,
    resolve_quality_prior,
)
from contextual_orchestrator.model_group import (
    BETA_PRIOR_FAILURE_COUNT,
    BETA_PRIOR_SUCCESS_COUNT,
)


def test_unknown_members_receive_the_unchanged_laplace_pair() -> None:
    """A member absent from every instrument keeps the repo default prior."""
    alpha, beta = resolve_quality_prior("totally-unknown-model")
    assert alpha == BETA_PRIOR_SUCCESS_COUNT
    assert beta == BETA_PRIOR_FAILURE_COUNT


def test_known_members_redistribute_exactly_the_prior_budget() -> None:
    """Measured priors preserve mass; a known member never gains evidence."""
    for key in ("gpt-4o", "claude-3-haiku", "mixtral-8x7b-instruct"):
        alpha, beta = resolve_quality_prior(f"openrouter/some-org/{key}")
        assert alpha >= 0.0 and beta >= 0.0
        total = alpha + beta
        assert total == PRIOR_EVIDENCE_BUDGET


def test_membership_is_monotone_in_the_published_ratings() -> None:
    """Higher published ratings map to strictly larger prior success share."""
    strong = measured_quality_probability("claude-3-5-sonnet")
    weak = measured_quality_probability("mixtral-8x7b-instruct")
    assert strong is not None and weak is not None
    assert strong > weak
    assert 0.0 < weak < strong < 1.0


def test_identifying_prefixes_do_not_change_measurements() -> None:
    """Provider prefixes are irrelevant to the shipped rating lookup."""
    plain = resolve_quality_prior("gpt-4o")
    prefixed = resolve_quality_prior("openrouter/company/gpt-4o-mini-suffix")
    # 'gpt-4o' substring matching must be deliberate: this pins the rule.
    assert plain[0] + plain[1] == PRIOR_EVIDENCE_BUDGET
    assert prefixed == plain


def test_derivation_is_deterministic_across_calls() -> None:
    """Repeated resolution returns identical tuples (no drift, no RNG)."""
    first = resolve_quality_prior("llama-3-70b-instruct")
    second = resolve_quality_prior("llama-3-70b-instruct")
    assert first == second
