"""Resource-bound contracts for strict NIM benchmark answer scoring."""

from __future__ import annotations

import pytest

from contextual_orchestrator import nim_benchmark as nb
from contextual_orchestrator import nim_strict_scoring as strict


def test_strict_answer_character_budget_is_explicit_and_bounded() -> None:
    """Keep answer-key and model-output normalization inside one reviewable cap."""
    assert strict.MAX_STRICT_ANSWER_CHARACTERS == 4096


def test_numeric_scorer_rejects_oversized_or_unrepresentable_model_answers() -> None:
    """Hostile numeric output must score zero rather than exhaust or abort the run."""
    oversized = "9" * (strict.MAX_STRICT_ANSWER_CHARACTERS + 1)
    exponent_overflow = "1e" + "9" * 80

    assert strict.score_exact_number_match_v2({"number": "9"}, oversized) == 0.0
    assert (
        strict.score_exact_number_match_v2(
            {"number": "9"},
            exponent_overflow,
        )
        == 0.0
    )


def test_numeric_answer_key_over_budget_fails_before_provider_egress() -> None:
    """An oversized expected literal is an invalid manifest, not a failed model cell."""
    oversized = "9" * (strict.MAX_STRICT_ANSWER_CHARACTERS + 1)

    with pytest.raises(nb.BenchmarkContractError, match="character budget"):
        strict.score_exact_number_match_v2({"number": oversized}, "9")


def test_text_scorer_rejects_oversized_model_answers_without_normalizing_them() -> None:
    """Oversized free text must score zero under both case policies."""
    oversized = "A" * (strict.MAX_STRICT_ANSWER_CHARACTERS + 1)

    assert strict.score_exact_text_match({"texts": ["A"]}, oversized) == 0.0
    assert (
        strict.score_exact_text_match(
            {"texts": ["A"], "case_sensitive": True},
            oversized,
        )
        == 0.0
    )


def test_text_answer_key_over_budget_fails_before_provider_egress() -> None:
    """Every declared alias must fit the same strict-scoring character budget."""
    oversized = "A" * (strict.MAX_STRICT_ANSWER_CHARACTERS + 1)

    with pytest.raises(nb.BenchmarkContractError, match="character budget"):
        strict.score_exact_text_match({"texts": [oversized]}, "A")
