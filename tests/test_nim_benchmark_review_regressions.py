"""Regression contracts for exact-head NIM benchmark review findings."""

from __future__ import annotations

from pathlib import Path

import pytest

from contextual_orchestrator import nim_benchmark as nb


REQUIRED_RENDER_PATHS = {
    "evaluation.observed_paired_task_count",
    "evaluation.observed_completion_fraction",
    "honesty_labels.hypothetical_cost_source",
}


def test_catalog_recursion_is_normalized_to_domain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Attacker-depth JSON must not leak a raw interpreter recursion failure."""
    def recurse(_text: str) -> object:
        raise RecursionError("synthetic decoder depth")

    monkeypatch.setattr(nb.json, "loads", recurse)

    with pytest.raises(nb.CatalogDiscoveryError, match="not valid JSON"):
        nb.parse_model_catalog_body(b'{"data": []}')


def test_pareto_frontiers_exclude_zero_success_policies() -> None:
    """A policy with no successful cells cannot appear buyer-competitive."""
    summaries = [
        {
            "policy_name": "successful_policy",
            "success_count": 1,
            "mean_task_score": 0.5,
            "mean_latency_ms": 10.0,
            "mean_hypothetical_cost_usd": 0.1,
        },
        {
            "policy_name": "failed_policy",
            "success_count": 0,
            "mean_task_score": 0.0,
            "mean_latency_ms": 0.0,
            "mean_hypothetical_cost_usd": 0.0,
        },
    ]

    frontiers = nb.build_pareto_frontiers(summaries)

    assert frontiers["excluded_zero_success_policies"] == ["failed_policy"]
    assert {
        row["policy_name"] for row in frontiers["quality_vs_latency"]
    } == {"successful_policy"}
    assert {
        row["policy_name"]
        for row in frontiers["quality_vs_hypothetical_cost"]
    } == {"successful_policy"}


def test_report_schema_requires_every_renderer_dependency() -> None:
    """Schema validation must guard fields read later by artifact renderers."""
    assert REQUIRED_RENDER_PATHS <= set(nb._REPORT_REQUIRED_PATHS)


def test_live_client_preserves_subsecond_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A positive fractional timeout must reach the provider client unchanged."""
    captured: dict[str, object] = {}

    class CapturingClient:
        """Constructor-only stand-in because evaluation is isolated below."""

        def __init__(self, _request_budget: object, **kwargs: object) -> None:
            captured.update(kwargs)

    manifest = {
        "manifest_version": "review-regression.1",
        "tasks": [{"task_id": "locked_review_task", "split": "locked"}],
    }
    catalog = {
        "models": [{"model_id": "vendor/model-one", "owned_by": "vendor"}],
        "duplicate_model_ids": [],
        "invalid_entries": [],
    }
    request_plan = {
        "catalog_request_count": 1,
        "capability_probe_request_count": 9,
        "evaluation_reserve_request_count": 8,
        "planned_worker_count": 1,
        "total_required_request_count": 18,
    }

    monkeypatch.setattr(nb, "_BudgetedModelClient", CapturingClient)
    monkeypatch.setattr(nb, "get_credential", lambda _name: "secret-test-key")
    monkeypatch.setattr(nb, "load_task_manifest", lambda _path: manifest)
    monkeypatch.setattr(nb, "load_pricing_scenario", lambda _path: None)
    monkeypatch.setattr(nb, "discover_model_catalog", lambda *_args: catalog)
    monkeypatch.setattr(nb, "plan_complete_request_budget", lambda **_kwargs: request_plan)
    monkeypatch.setattr(nb, "probe_discovered_models", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(nb, "build_worker_agents", lambda *_args: [object()])
    monkeypatch.setattr(
        nb,
        "evaluate_policies",
        lambda *_args, **_kwargs: {
            "evaluation_cells": [],
            "cheapest_worker_skip_reason": None,
            "locked_task_count": 1,
            "worker_count": 1,
        },
    )
    monkeypatch.setattr(nb, "assemble_benchmark_report", lambda *_args: {})
    monkeypatch.setattr(nb, "write_benchmark_artifacts", lambda *_args: {})

    nb.run_benchmark(
        "live",
        "ignored.json",
        None,
        str(tmp_path),
        max_total_requests=18,
        timeout_seconds=0.25,
        git_sha="a" * 40,
        workflow_run_id="123",
        transport=lambda *_args: (200, b"{}"),
    )

    assert captured["timeout"] == 0.25
