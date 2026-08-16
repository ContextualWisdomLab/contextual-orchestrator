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

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.reasoning_effort_profile import (  # noqa: E402
    PROFILE_VERSION,
    PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD,
    WORKFLOW_ROLES,
    EffortProfileError,
    default_role_effort_catalog,
    estimate_theta,
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


def test_parse_rejects_missing_payload_and_blank_version() -> None:
    try:
        parse_reasoning_effort_profile(None)
    except EffortProfileError:
        pass
    else:
        raise AssertionError("missing profile must fail closed")
    try:
        parse_reasoning_effort_profile({"profile_version": ""})
    except EffortProfileError:
        return
    raise AssertionError("blank profile_version must fail closed")


def test_parse_rejects_fractional_seed() -> None:
    try:
        parse_reasoning_effort_profile({"seed": 7.9})
    except EffortProfileError:
        return
    raise AssertionError("fractional seed must fail closed")


def test_catalog_snapshot_is_stable_and_replayable() -> None:
    first = snapshot_role_effort_catalog(default_role_effort_catalog())
    second = snapshot_role_effort_catalog(default_role_effort_catalog())
    assert first.snapshot_hash == second.snapshot_hash
    assert first.profile_version == PROFILE_VERSION
    assert set(first.role_profiles) == set(WORKFLOW_ROLES)


def test_snapshot_rejects_incomplete_or_extra_roles() -> None:
    catalog = default_role_effort_catalog()
    incomplete = {role: catalog[role] for role in ("thinker", "worker")}
    try:
        snapshot_role_effort_catalog(incomplete)
    except EffortProfileError:
        pass
    else:
        raise AssertionError("incomplete catalog must fail closed")
    extra = dict(catalog)
    extra["critic"] = catalog["judge"]
    try:
        snapshot_role_effort_catalog(extra)
    except EffortProfileError:
        return
    raise AssertionError("extra catalog roles must fail closed")


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
    estimate = estimate_theta(
        true_theta,
        reasoning_effort="medium",
        extra_workflow_steps=0,
        extra_recursion_depth=0,
        access_list_scope="role",
        temperature=0.2,
    )
    assert len(estimate.estimated_theta) == len(true_theta)
    residuals = [
        hat - value for hat, value in zip(estimate.estimated_theta, true_theta)
    ]
    expected_rmse = math.sqrt(sum(error * error for error in residuals) / len(residuals))
    assert math.isclose(estimate.rmse, expected_rmse, rel_tol=1e-12, abs_tol=1e-12)


def test_true_theta_values_change_estimated_rmse() -> None:
    compact = estimate_theta_rmse(
        (-1.5, 0.0, 1.5),
        reasoning_effort="medium",
        extra_workflow_steps=0,
        temperature=0.2,
    )
    wide = estimate_theta_rmse(
        (100.0, 200.0, 300.0),
        reasoning_effort="medium",
        extra_workflow_steps=0,
        temperature=0.2,
    )
    assert compact != wide


def test_empty_true_theta_fails_closed() -> None:
    try:
        estimate_theta_rmse((), reasoning_effort="medium", extra_workflow_steps=0, temperature=0.2)
    except EffortProfileError:
        return
    raise AssertionError("empty true_theta must fail closed")


def test_access_list_scope_changes_rmse() -> None:
    true_theta = (-1.2, -0.4, 0.2, 0.8, 1.4)
    role_scope = estimate_theta_rmse(
        true_theta,
        reasoning_effort="high",
        extra_workflow_steps=3,
        extra_recursion_depth=0,
        access_list_scope="role",
        temperature=0.2,
    )
    workflow_scope = estimate_theta_rmse(
        true_theta,
        reasoning_effort="high",
        extra_workflow_steps=3,
        extra_recursion_depth=0,
        access_list_scope="workflow",
        temperature=0.2,
    )
    assert role_scope != workflow_scope


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
    assert report["one_factor_ablations"]["access_list_scope"]["role"] != report[
        "one_factor_ablations"
    ]["access_list_scope"]["workflow"]
    assert "estimated_theta" in report["single_model_baseline"]
    assert len(report["single_model_baseline"]["estimated_theta"]) == 5
    assert report["single_model_baseline"]["estimated_tokens_used"] <= report[
        "single_model_baseline"
    ]["budget_tokens"]
    assert report["role_differentiated"]["estimated_tokens_used"] <= report[
        "role_differentiated"
    ]["budget_tokens"]


def test_production_gate_rejects_junk_and_estimated_status() -> None:
    assert production_default_change_allowed({}) is False
    report = run_equal_budget_ablation(true_theta=(-1.2, -0.4, 0.2, 0.8, 1.4))
    unlocked = dict(report)
    unlocked["robustness_passed"] = True
    unlocked["measurement_status"] = "estimated"
    assert production_default_change_allowed(unlocked) is False


def test_opt_in_catalog_attaches_identical_snapshot_on_route_and_conduct() -> None:
    catalog = default_role_effort_catalog()
    expected = snapshot_role_effort_catalog(catalog).snapshot_hash
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation"), priority=1),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review"), priority=2),
        ],
        role_effort_catalog=catalog,
    )
    routed = orchestrator.complete([{"role": "user", "content": "Write one sentence."}], mode="route")
    conducted = orchestrator.complete(
        [{"role": "user", "content": "Analyze the architecture, implement the code, and verify risks."}],
        mode="conduct",
    )
    assert routed["reasoning_effort_snapshot"]["snapshot_hash"] == expected
    assert conducted["reasoning_effort_snapshot"]["snapshot_hash"] == expected
    assert routed["reasoning_effort_snapshot"]["profile_version"] == PROFILE_VERSION
    defaulted = TaskOrchestrator(
        [ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning"))]
    ).complete([{"role": "user", "content": "Write one sentence."}], mode="route")
    assert "reasoning_effort_snapshot" not in defaulted


def test_persisted_run_stream_and_batch_keep_snapshot() -> None:
    catalog = default_role_effort_catalog()
    expected = snapshot_role_effort_catalog(catalog).snapshot_hash
    orchestrator = TaskOrchestrator(
        [ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning"))],
        role_effort_catalog=catalog,
    )
    persisted = orchestrator.run(
        [{"role": "user", "content": "Write one sentence."}],
        mode="route",
    )
    assert persisted["reasoning_effort_snapshot"]["snapshot_hash"] == expected
    stream_id = "run_effort_stream_persist"
    list(
        orchestrator.stream_route(
            [{"role": "user", "content": "Write one sentence."}],
            workflow_run_id=stream_id,
        )
    )
    streamed = orchestrator.get_workflow_run(stream_id)
    assert streamed["reasoning_effort_snapshot"]["snapshot_hash"] == expected
    batched = orchestrator.batch_route(["Write one sentence."])
    assert batched[0]["reasoning_effort_snapshot"]["snapshot_hash"] == expected


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
        assert "Baker, F. B. (2001)" in document


if __name__ == "__main__":  # pragma: no cover
    test_parse_rejects_unknown_profile_keys()
    test_parse_rejects_nan_infinity_and_boolean_numbers()
    test_reasoning_effort_is_not_a_temperature_proxy()
    test_parse_rejects_missing_payload_and_blank_version()
    test_parse_rejects_fractional_seed()
    test_default_catalog_binds_every_workflow_role()
    test_catalog_snapshot_is_stable_and_replayable()
    test_snapshot_rejects_incomplete_or_extra_roles()
    test_true_theta_rmse_improves_with_effort_not_temperature()
    test_true_theta_values_change_estimated_rmse()
    test_empty_true_theta_fails_closed()
    test_access_list_scope_changes_rmse()
    test_equal_budget_ablation_keeps_production_default_locked()
    test_production_gate_rejects_junk_and_estimated_status()
    test_opt_in_catalog_attaches_identical_snapshot_on_route_and_conduct()
    test_persisted_run_stream_and_batch_keep_snapshot()
    test_doctoring_cites_fugu_trinity_conductor_apa7()
    print("ok")
