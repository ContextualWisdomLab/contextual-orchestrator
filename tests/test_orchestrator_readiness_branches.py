"""Targeted coverage for readiness-report and analytics-helper branches.

These drive the previously-uncovered ``fail``/``blocked`` status branches of the
commercial/sales/buyer readiness reports (via an insecure ``security_profile``),
the security/locale/provider-egress criterion generators, the workflow-trace and
policy-safety analytics helpers (via crafted workflow runs), and the
generated-plan model-judge paths — all through the public report/analytics
surface, asserting on the returned status and evidence.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_TRANSLATIONS  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


INSECURE_PROFILE = {
    "auth_mode": "loopback_no_auth",
    "allow_public_bind": True,
    "expose_trace_by_default": True,
    "rate_limit_requests": 0,
    "max_concurrent_runs": 0,
}

SECURE_PROFILE = {
    "auth_mode": "split_token",
    "allow_public_bind": False,
    "expose_trace_by_default": False,
    "rate_limit_requests": 60,
    "max_concurrent_runs": 8,
}


def build() -> TaskOrchestrator:
    """A three-agent mock pool covering planning, coding, and review roles."""
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review")),
        ]
    )


def criteria_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index a report's criteria rows by criterion_name."""
    return {str(row["criterion_name"]): row for row in report["criteria"]}


# -- Security-posture, locale, and provider-egress criterion generators --------


def test_security_posture_criterion_fails_on_insecure_profile() -> None:
    """Every insecure control aggregates into a single failing security criterion."""
    report = build().sales_readiness_report(locale_bundles=ADMIN_TRANSLATIONS, security_profile=INSECURE_PROFILE)
    rows = criteria_by_name(report)
    security = rows["security_posture"]
    assert report["readiness_status"] == "not_ready"
    assert security["status"] == "fail"
    for expected in (
        "no bearer token configured",
        "public bind is enabled",
        "trace exposure is enabled by default",
        "request rate limiting is disabled",
        "run concurrency limiting is disabled",
    ):
        assert expected in security["evidence"]


def test_locale_readiness_criterion_warns_on_missing_korean_keys() -> None:
    """Partial locale parity with named missing keys is a warning, not a pass."""
    bundles = {"en": {"first_key": "A", "second_key": "B"}, "ko": {"first_key": "가"}}
    report = build().sales_readiness_report(locale_bundles=bundles, security_profile=SECURE_PROFILE)
    locale = criteria_by_name(report)["locale_readiness"]
    assert locale["status"] == "warn"
    assert "ko.second_key" in locale["evidence"]


def test_locale_readiness_criterion_fails_when_bundles_absent() -> None:
    """No comparable locale bundles fails locale readiness with the absent-bundle note."""
    report = build().sales_readiness_report(locale_bundles={}, security_profile=SECURE_PROFILE)
    locale = criteria_by_name(report)["locale_readiness"]
    assert locale["status"] == "fail"
    assert "locale bundles absent" in locale["evidence"]


def test_provider_egress_criterion_fails_for_non_https_remote_agent() -> None:
    """A non-mock agent on plain http is flagged as unsafe provider egress."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning", "verification")),
            ModelAgent("insecure_remote_agent", "gpt-x", base_url="http://provider.example/v1"),
        ]
    )
    report = orchestrator.sales_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS, security_profile=SECURE_PROFILE
    )
    egress = criteria_by_name(report)["provider_egress_safety"]
    assert egress["status"] == "fail"
    assert "insecure_remote_agent" in egress["evidence"]


# -- Report fail/blocked status branches (insecure profile) --------------------


def test_reports_reach_blocked_status_on_insecure_profile() -> None:
    """The insecure profile drives each report into its concrete fail/blocked branch."""
    orchestrator = build()
    kwargs = {"locale_bundles": {}, "security_profile": INSECURE_PROFILE}

    assert orchestrator.sales_readiness_report(
        locale_bundles={}, security_profile=INSECURE_PROFILE
    )["readiness_status"] == "not_ready"
    assert orchestrator.commercial_readiness_report(**kwargs)["commercial_status"] == "not_commercial_ready"
    assert orchestrator.buyer_evidence_manifest_report(**kwargs)["manifest_status"] == "buyer_review_blocked"
    assert orchestrator.buyer_handoff_bundle_report(**kwargs)["bundle_status"] == "buyer_handoff_blocked"

    saleability = orchestrator.saleability_decision_report(**kwargs)
    assert saleability["saleability_status"] == "saleability_blocked"
    assert saleability["decision_label"] == "Blocked by concrete defect"

    assert orchestrator.commercial_evidence_export_report(**kwargs)["export_status"] == "commercial_export_blocked"
    assert orchestrator.commercial_acceptance_check_report(**kwargs)["acceptance_status"] == (
        "commercial_acceptance_blocked"
    )
    assert orchestrator.commercial_release_candidate_report(**kwargs)["release_status"] == (
        "commercial_release_blocked"
    )
    assert orchestrator.commercial_gap_register_report(**kwargs)["gap_register_status"] == (
        "commercial_gap_register_blocked"
    )
    assert orchestrator.commercial_procurement_readiness_report(**kwargs)["procurement_status"] == (
        "commercial_procurement_blocked"
    )
    assert orchestrator.commercial_contract_readiness_report(**kwargs)["contract_status"] == (
        "commercial_contract_blocked"
    )
    assert orchestrator.commercial_onboarding_readiness_report(**kwargs)["onboarding_status"] == (
        "commercial_onboarding_blocked"
    )
    assert orchestrator.commercial_operations_readiness_report(**kwargs)["operations_status"] == (
        "commercial_operations_blocked"
    )
    assert orchestrator.commercial_security_attestation_report(**kwargs)["security_attestation_status"] == (
        "commercial_security_attestation_blocked"
    )
    assert orchestrator.commercial_value_readiness_report(**kwargs)["value_status"] == "commercial_value_blocked"


def test_aggregate_reports_reach_blocked_status_without_crashing() -> None:
    """The dedup-reports return their blocked status on real (dict) blocker artifacts.

    Regression for the ``dict.fromkeys(concrete_blockers)`` crash: an insecure profile
    produces blocked evidence-item artifacts (dicts) that flow into these aggregate
    reports; each must report ``*_blocked`` rather than raise ``TypeError``.
    """
    orchestrator = build()
    kwargs = {"locale_bundles": {}, "security_profile": INSECURE_PROFILE}

    assert orchestrator.commercial_close_readiness_report(**kwargs)["close_status"] == "commercial_close_blocked"
    assert orchestrator.commercial_go_to_market_readiness_report(**kwargs)["go_to_market_status"] == (
        "commercial_go_to_market_blocked"
    )
    assert orchestrator.commercial_launch_readiness_report(**kwargs)["launch_status"] == "commercial_launch_blocked"
    assert orchestrator.commercial_buyer_acceptance_workflow_report(**kwargs)["workflow_status"] == (
        "buyer_acceptance_workflow_blocked"
    )

    completion = orchestrator.commercial_completion_scorecard_report(**kwargs)
    assert completion["completion_status"] == "commercial_completion_blocked"
    # The two string markers appended only on the not-ready / launch-blocked path.
    assert "commercial_readiness_failed" in completion["concrete_blockers"]
    assert "commercial_launch_blocked" in completion["concrete_blockers"]


# -- Workflow-trace completeness and policy-safety analytics helpers -----------


def _base_step(**overrides: object) -> dict[str, object]:
    step = {"id": 0, "role": "worker", "agent_id": "planner_agent", "subtask": "s", "access": [], "output": "o"}
    step.update(overrides)
    return step


def _conduct_run(run_id: str, **overrides: object) -> dict[str, object]:
    run = {
        "workflow_run_id": run_id,
        "created_at": 0,
        "mode": "conduct",
        "policy_mode": "conduct",
        "prompt_text": "prompt",
        "answer": "answer",
        "trace": [_base_step()],
        "policy_snapshot": {"verifier_required": True},
        "verification": {"accepted": True, "reason": "ok", "verifier_output": ""},
    }
    run.update(overrides)
    return run


def test_trace_completeness_rejects_malformed_conducted_runs() -> None:
    """Empty, key-missing, and non-list-access traces all count as incomplete."""
    orchestrator = build()
    orchestrator._workflow_runs["run_empty"] = _conduct_run("run_empty", trace=[])
    orchestrator._workflow_runs["run_missing_key"] = _conduct_run(
        "run_missing_key",
        trace=[{"id": 0, "role": "worker", "agent_id": "planner_agent", "subtask": "s", "access": []}],
    )
    orchestrator._workflow_runs["run_bad_access"] = _conduct_run(
        "run_bad_access", trace=[_base_step(access="not-a-list")]
    )
    snapshot = orchestrator.analytics_snapshot()
    trace_metric = next(m for m in snapshot["kpis"] if m["metric_name"] == "trace_complete_workflow_rate")
    assert trace_metric["numerator"] == 0
    assert trace_metric["denominator"] == 3


def test_policy_safe_routing_rejects_conduct_run_without_verification() -> None:
    """A verifier-required conduct run with no verification is not policy-safe."""
    orchestrator = build()
    orchestrator._workflow_runs["run_unverified"] = _conduct_run("run_unverified", verification=None)
    snapshot = orchestrator.analytics_snapshot()
    policy_metric = next(m for m in snapshot["kpis"] if m["metric_name"] == "policy_safe_routing_rate")
    assert policy_metric["numerator"] == 0
    assert policy_metric["denominator"] == 1


def test_provider_exclusion_miss_count_flags_ghost_and_excluded_roles() -> None:
    """Unknown agent ids and role-excluded agents each register as an exclusion miss."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent(
                "excluded_review_agent",
                "mock-reviewer",
                tags=("verification", "review"),
                provider_exclusions=("worker",),
            ),
        ]
    )
    orchestrator._workflow_runs["run_misses"] = {
        "workflow_run_id": "run_misses",
        "created_at": 0,
        "mode": "conduct",
        "policy_mode": "conduct",
        "prompt_text": "p",
        "answer": "a",
        "trace": [
            _base_step(id=0, role="worker", agent_id="excluded_review_agent"),
            _base_step(id=1, role="worker", agent_id="ghost_agent"),
        ],
        "policy_snapshot": {"verifier_required": False},
        "verification": {"accepted": True, "reason": "ok", "verifier_output": ""},
    }
    snapshot = orchestrator.analytics_snapshot()
    guardrail = next(m for m in snapshot["guardrails"] if m["metric_name"] == "provider_exclusion_miss_rate")
    assert guardrail["value"] == 2


# -- Generated-plan model-judge conduct paths ----------------------------------


class _GeneratedPlanClient(ModelClient):
    """Returns a scripted plan on call 1, then scripted step/judge replies by index."""

    def __init__(self, plan_text: str, replies: dict[int, str]) -> None:
        super().__init__()
        self._plan_text = plan_text
        self._replies = replies
        self.calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls += 1
        if self.calls == 1:
            return self._plan_text
        return self._replies.get(self.calls, f"step-output({self.calls})")


def _generated_orchestrator(plan_text: str, replies: dict[int, str]) -> tuple[TaskOrchestrator, _GeneratedPlanClient]:
    client = _GeneratedPlanClient(plan_text, replies)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research", "verification"))],
        client=client,
    )
    orchestrator.policy = replace(orchestrator.policy, workflow_planning="generated", verifier_judge="model")
    return orchestrator, client


def test_generated_plan_model_judge_reject_falls_back_to_worker_output() -> None:
    """A model-judge REJECT on a generated plan returns the worker output as the answer."""
    plan = json.dumps({
        "steps": [
            {"id": 0, "role": "worker", "agent_id": "general_agent", "subtask": "Draft the solution.", "access": []},
            {"id": 1, "role": "verifier", "agent_id": "general_agent", "subtask": "Check the draft.", "access": [0]},
            {"id": 2, "role": "synthesizer", "agent_id": "general_agent", "subtask": "Finalize.", "access": [0, 1]},
        ]
    })
    replies = {2: "worker-draft", 3: "verifier says look at this", 4: "final-synth", 5: "REJECT"}
    orchestrator, client = _generated_orchestrator(plan, replies)
    result = orchestrator.conduct([{"role": "user", "content": "solve the hard problem"}])
    assert result["plan_source"] == "generated"
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge"] == "model"
    assert result["answer"] == "worker-draft"
    assert client.calls == 5  # plan + 3 steps + 1 judge call


def test_generated_plan_model_judge_skips_when_no_verifier_output() -> None:
    """With no verifier step, the model judge keeps the fallback and makes no judge call."""
    plan = json.dumps({
        "steps": [
            {"id": 0, "role": "worker", "agent_id": "general_agent", "subtask": "Do the work.", "access": []},
            {"id": 1, "role": "synthesizer", "agent_id": "general_agent", "subtask": "Finalize.", "access": [0]},
        ]
    })
    replies = {2: "worker-out", 3: "synth-out"}
    orchestrator, client = _generated_orchestrator(plan, replies)
    result = orchestrator.conduct([{"role": "user", "content": "solve the hard problem"}])
    assert result["plan_source"] == "generated"
    assert result["verification"]["accepted"] is True
    assert "judge" not in result["verification"]
    assert result["answer"] == "synth-out"
    assert client.calls == 3  # plan + 2 steps, no judge call


def test_parse_workflow_plan_rejects_empty_subtask() -> None:
    """A generated step with a blank subtask is a structural rejection."""
    orchestrator, _ = _generated_orchestrator("{}", {})
    plan = json.dumps({
        "steps": [
            {"id": 0, "role": "worker", "agent_id": "general_agent", "subtask": "", "access": []},
            {"id": 1, "role": "synthesizer", "agent_id": "general_agent", "subtask": "b", "access": []},
        ]
    })
    raised = False
    try:
        orchestrator._parse_workflow_plan(plan)
    except ValueError as exc:
        raised = True
        assert "subtask" in str(exc)
    assert raised


if __name__ == "__main__":  # pragma: no cover
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"ok {name}")
    print("ok")
