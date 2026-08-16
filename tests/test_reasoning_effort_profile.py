"""Issue #568: provider-neutral role reasoning-effort profiles and ablation.

Buyer next action: load a versioned ``reasoning_effort_profile`` per workflow
role, compare equal-budget variants against true parameters, and keep the
production default unchanged until the predeclared RMSE threshold is met.
Sampling temperature is not reasoning effort.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.reasoning_effort_profile import (  # noqa: E402
    PROFILE_VERSION,
    PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD,
    WORKFLOW_ROLES,
    EffortProfileError,
    default_role_effort_catalog,
    estimate_theta_rmse,
    parse_reasoning_effort_profile,
    production_default_change_allowed,
    run_equal_budget_ablation,
    snapshot_role_effort_catalog,
)


def test_parse_rejects_unknown_profile_keys() -> None:
    try:
        parse_reasoning_effort_profile({"reasoning_effort": "high", "mystery_knob": 1})
    except EffortProfileError as exc:
        assert "unknown" in str(exc).lower()
        return
    raise AssertionError("unknown profile keys must fail closed")


def test_parse_rejects_nan_infinity_and_boolean_numbers() -> None:
    for raw in (
        {"max_output_tokens": math.nan},
        {"max_output_tokens": math.inf},
        {"max_workflow_steps": True},
        {"temperature": False},
    ):
        try:
            parse_reasoning_effort_profile(raw)
        except EffortProfileError:
            continue
        raise AssertionError(f"invalid numeric {raw!r} must fail closed")


def test_reasoning_effort_is_not_a_temperature_proxy() -> None:
    high = parse_reasoning_effort_profile(
        {"reasoning_effort": "high", "temperature": 0.2, "top_p": 0.9, "seed": 7}
    )
    assert high.reasoning_effort == "high"
    assert high.temperature == 0.2
    assert high.top_p == 0.9
    assert high.seed == 7
    try:
        parse_reasoning_effort_profile({"reasoning_effort": 0.9})
    except EffortProfileError:
        return
    raise AssertionError("numeric reasoning_effort must not coerce to temperature")


def test_default_catalog_binds_every_workflow_role() -> None:
    catalog = default_role_effort_catalog()
    assert set(catalog) == set(WORKFLOW_ROLES)
    assert catalog["thinker"].reasoning_effort == "high"
    assert catalog["worker"].reasoning_effort == "medium"
    assert catalog["verifier"].reasoning_effort == "high"
    assert catalog["synthesizer"].reasoning_effort == "medium"
    assert catalog["planner"].reasoning_effort == "high"
    assert catalog["judge"].reasoning_effort == "high"
    for profile in catalog.values():
        assert profile.profile_version == PROFILE_VERSION
        assert profile.max_calls >= 1
        assert profile.max_workflow_steps >= 1


def test_catalog_snapshot_is_stable_and_replayable() -> None:
    first = snapshot_role_effort_catalog(default_role_effort_catalog())
    second = snapshot_role_effort_catalog(default_role_effort_catalog())
    assert first.snapshot_hash == second.snapshot_hash
    assert first.profile_version == PROFILE_VERSION
    assert set(first.role_profiles) == set(WORKFLOW_ROLES)


def test_true_theta_rmse_improves_with_effort_not_temperature() -> None:
    true_theta = (-1.5, -0.5, 0.0, 0.5, 1.5)
    baseline = estimate_theta_rmse(
        true_theta,
        reasoning_effort="medium",
        extra_workflow_steps=0,
        temperature=0.2,
    )
    high_effort = estimate_theta_rmse(
        true_theta,
        reasoning_effort="high",
        extra_workflow_steps=0,
        temperature=0.2,
    )
    temperature_proxy = estimate_theta_rmse(
        true_theta,
        reasoning_effort="medium",
        extra_workflow_steps=0,
        temperature=1.0,
    )
    assert high_effort < baseline
    assert math.isclose(temperature_proxy, baseline, rel_tol=1e-9, abs_tol=1e-12)


def test_equal_budget_ablation_keeps_production_default_locked() -> None:
    report = run_equal_budget_ablation(true_theta=(-1.2, -0.4, 0.2, 0.8, 1.4))
    assert report["single_model_baseline"]["mode"] == "route"
    assert report["role_differentiated"]["mode"] == "conduct"
    assert report["role_differentiated"]["budget_tokens"] == report["single_model_baseline"]["budget_tokens"]
    assert set(report["one_factor_ablations"]) >= {
        "reasoning_effort",
        "temperature",
        "recursion_depth",
        "workflow_steps",
        "access_list_scope",
    }
    assert report["route_versus_conduct"]["route"]["rmse"] >= 0
    assert report["route_versus_conduct"]["conduct"]["rmse"] >= 0
    assert report["measurement_status"] == "estimated"
    assert production_default_change_allowed(report) is False
    assert PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD > 0


def test_doctoring_cites_fugu_trinity_conductor_apa7() -> None:
    root = Path(__file__).resolve().parents[1]
    architecture = (root / "docs" / "architecture.md").read_text(encoding="utf-8")
    papers = (root / "docs" / "papers" / "README.md").read_text(encoding="utf-8")
    for document in (architecture, papers):
        assert "Sakana AI. (2026)" in document
        assert "Xu, J." in document
        assert "Nielsen, S." in document
        assert "arXiv:2512.04695" in document
        assert "arXiv:2512.04388" in document
        assert "reasoning_effort_profile" in document


if __name__ == "__main__":  # pragma: no cover
    test_parse_rejects_unknown_profile_keys()
    test_parse_rejects_nan_infinity_and_boolean_numbers()
    test_reasoning_effort_is_not_a_temperature_proxy()
    test_default_catalog_binds_every_workflow_role()
    test_catalog_snapshot_is_stable_and_replayable()
    test_true_theta_rmse_improves_with_effort_not_temperature()
    test_equal_budget_ablation_keeps_production_default_locked()
    test_doctoring_cites_fugu_trinity_conductor_apa7()
    print("ok")
