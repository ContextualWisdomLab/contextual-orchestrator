"""Regression contracts for optimizer selection and test-time search authority."""

from __future__ import annotations

import pytest

from contextual_orchestrator.orchestrator import (
    _recommend_config,
    evolve_orchestration,
    optimize_orchestration,
)


def test_tradeoff_has_no_invented_recommendation() -> None:
    rows = [
        {"name": "cheap", "quality": 0.60, "cost_usd": 0.01},
        {"name": "strong", "quality": 0.90, "cost_usd": 0.10},
    ]
    assert _recommend_config(rows, None) is None


def test_budget_with_no_admissible_candidate_has_no_cheapest_fallback() -> None:
    rows = [
        {"name": "a", "quality": 0.70, "cost_usd": 0.10},
        {"name": "b", "quality": 0.80, "cost_usd": 0.20},
    ]
    assert _recommend_config(rows, 0.05) is None


def test_unique_pareto_dominant_candidate_is_mathematically_identified() -> None:
    rows = [
        {"name": "dominating", "quality": 0.90, "cost_usd": 0.10},
        {"name": "dominated", "quality": 0.80, "cost_usd": 0.20},
    ]
    assert _recommend_config(rows, None) == {
        "name": "dominating",
        "quality": 0.90,
        "cost_usd": 0.10,
        "reason": "unique Pareto-dominant measured config",
    }


def test_optimizer_without_executable_evaluation_contract_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="validated evaluation adapter"):
        optimize_orchestration([], [], lambda _task, _answer: 1.0)


def test_fast_mlsirm_string_label_cannot_fake_executable_provenance() -> None:
    with pytest.raises(RuntimeError, match="fast-mlsirm-backed"):
        optimize_orchestration(
            [],
            [],
            lambda _task, _answer: 1.0,
            quality_evidence_kind="fast_mlsirm",
        )


def test_deterministic_label_alone_cannot_authorize_sampling_or_aggregation() -> None:
    with pytest.raises(RuntimeError, match="validated evaluation adapter"):
        optimize_orchestration(
            [],
            [],
            lambda _task, _answer: 1.0,
            quality_evidence_kind="deterministic_ground_truth",
        )


def test_ad_hoc_evolutionary_search_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="validated learned coordinator or research-backed search implementation"):
        evolve_orchestration(
            lambda _config: None,
            {"mode": ["route"]},
            [],
            lambda _task, _answer: 1.0,
            generations=1,
            population=1,
            seed=1,
        )
