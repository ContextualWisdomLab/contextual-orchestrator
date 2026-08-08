"""Behavioural coverage for orchestration and commercial-readiness branches.

The cases in this module exercise public and internal decision paths that are
not reached by the feature suites: provider-client TLS validation, non-mock
chat delegation, Batch parsing, Responses input coercion, generated planning,
model-judge fallback, lifecycle and budget handling, criterion helpers, cache
normalization, and blocked commercial-readiness classifications. Every case
asserts product behaviour rather than executing lines only.
"""

from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_TRANSLATIONS  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import (  # noqa: E402
    BudgetExceededError,
    ModelClient,
    _coerce_input_text,
    _freeze_report_cache_value,
    _recommend_config,
)


def test_build_ssl_context_rejects_unloadable_ca_bundle() -> None:
    """A present but invalid custom CA bundle fails with a bounded ValueError."""
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
        handle.write("this is not a certificate\n")
        bundle_path = handle.name
    try:
        with pytest.raises(ValueError) as exc:
            ModelClient._build_ssl_context(bundle_path, verify_tls=True)
        assert "could not be loaded" in str(exc.value)
    finally:
        Path(bundle_path).unlink()


def test_chat_delegates_non_mock_agent_to_send_with_retry() -> None:
    """Configured non-mock chat validates then delegates to the retrying sender."""
    set_backend(InMemoryCredentialBackend())
    register_credential("OPENAI_API_KEY", "sk-live")
    try:
        client = ModelClient()
        client._validate_provider = lambda agent: None  # type: ignore[assignment]
        client._send_with_retry = lambda agent, payload: "provider replied"  # type: ignore[assignment]
        agent = ModelAgent("remote_agent", "gpt-x", "https://api.example-provider.com/v1")
        assert client.chat(agent, [{"role": "user", "content": "hi"}]) == "provider replied"
    finally:
        set_backend(None)


def test_batch_run_parses_results_and_ignores_blank_lines() -> None:
    """Batch result parsing preserves rows and ignores blank JSONL separators."""

    class _FakeBatchClient(ModelClient):
        def _batch_upload(self, agent, payload):  # type: ignore[override]
            return "file-in"

        def _batch_json(self, agent, method, path, payload=None):  # type: ignore[override]
            if method == "POST" and path == "/batches":
                return {"id": "batch-1"}
            if path.startswith("/batches/"):
                return {"status": "completed", "output_file_id": "file-out"}
            raise AssertionError(f"unexpected batch call: {method} {path}")

        def _batch_raw(self, agent, path):  # type: ignore[override]
            rows = [
                json.dumps(
                    {
                        "custom_id": "task_0",
                        "response": {
                            "body": {
                                "choices": [{"message": {"content": "A"}}],
                                "usage": {"completion_tokens": 3},
                            }
                        },
                    }
                ),
                "",
                json.dumps(
                    {
                        "custom_id": "task_1",
                        "response": {"body": {"choices": [{"message": {"content": "B"}}]}},
                    }
                ),
            ]
            return "\n".join(rows).encode("utf-8")

    client = _FakeBatchClient()
    client._sleep = lambda _seconds: None
    agent = ModelAgent("remote_agent", "gpt-x", "https://api.example-provider.com/v1")
    results = client._batch_run(
        agent,
        {"task_0": [{"role": "user", "content": "a"}], "task_1": [{"role": "user", "content": "b"}]},
        temperature=0.2,
        poll_interval=0.0,
        poll_timeout=5.0,
    )
    assert results["task_0"]["content"] == "A"
    assert results["task_0"]["usage"] == {"completion_tokens": 3}
    assert results["task_1"]["content"] == "B"
    assert results["task_1"]["usage"] is None


def test_coerce_input_text_flattens_strings_dicts_and_content_lists() -> None:
    """Responses input coercion walks only supported text-bearing shapes."""
    value = [
        "plain string",
        {"content": "dict content"},
        {"content": [{"text": "chunk text"}, {"no_text": 1}]},
        {"other": "ignored"},
    ]
    assert _coerce_input_text(value) == "plain string dict content chunk text"
    assert _coerce_input_text("already a string") == "already a string"


_GENERATED_PLAN = {
    "steps": [
        {"id": 0, "role": "worker", "agent_id": "general_agent", "subtask": "Draft the answer.", "access": []},
        {"id": 1, "role": "worker", "agent_id": "general_agent", "subtask": "Draft an alternative.", "access": []},
        {"id": 2, "role": "verifier", "agent_id": "general_agent", "subtask": "Check both drafts.", "access": [0, 1]},
        {"id": 3, "role": "synthesizer", "agent_id": "general_agent", "subtask": "Merge into final.", "access": [1, 2]},
    ]
}


class _JudgeRejectClient(ModelClient):
    """Return a scripted generated plan and reject the verifier output."""

    def __init__(self, plan_text: str) -> None:
        super().__init__()
        self.plan_text = plan_text

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        system = messages[0].get("content", "") if messages else ""
        if "workflow conductor" in system:
            return self.plan_text
        if "verification judge" in system:
            return "REJECT"
        return "step output"


def _generated_orchestrator() -> TaskOrchestrator:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research", "verification"))],
        client=_JudgeRejectClient(json.dumps(_GENERATED_PLAN)),
    )
    orchestrator.policy = replace(
        orchestrator.policy,
        workflow_planning="generated",
        verifier_judge="model",
        verifier_required=True,
    )
    return orchestrator


def test_generated_plan_with_model_judge_rejection_falls_back_to_worker_answer() -> None:
    """A required verifier rejection cannot promote synthesizer output."""
    orchestrator = _generated_orchestrator()
    result = orchestrator.conduct([{"role": "user", "content": "solve the hard problem"}])
    assert result["plan_source"] == "generated"
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge"] == "model"
    assert result["answer"] == "step output"


def test_parse_workflow_plan_rejects_empty_subtask() -> None:
    """Generated workflow steps require a non-empty subtask."""
    orchestrator = _generated_orchestrator()
    plan = json.dumps(
        {
            "steps": [
                {"id": 0, "role": "worker", "agent_id": "general_agent", "subtask": "  ", "access": []},
                {"id": 1, "role": "synthesizer", "agent_id": "general_agent", "subtask": "merge", "access": [0]},
            ]
        }
    )
    with pytest.raises(ValueError) as exc:
        orchestrator._parse_workflow_plan(plan)
    assert "subtask must be non-empty" in str(exc.value)


def test_model_judge_verification_keeps_fallback_when_no_verifier_output() -> None:
    """An empty verifier answer leaves the deterministic fallback unchanged."""
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "m", tags=("reasoning", "verification"))])
    fallback = {"accepted": True, "reason": "term-based", "verifier_output": ""}
    assert orchestrator._model_judge_verification("task", fallback) is fallback


def test_spend_analytics_reports_mixed_usage_source() -> None:
    """Mixed provider-reported and estimated usage is identified explicitly."""
    orchestrator = TaskOrchestrator([ModelAgent("worker_agent", "model-x", tags=("reasoning", "writing"))])
    orchestrator._workflow_runs["run_reported"] = {
        "prompt_text": "prompt",
        "trace": [{"agent_id": "worker_agent", "output": "aaaa", "usage": {"completion_tokens": 5}}],
    }
    orchestrator._workflow_runs["run_estimated"] = {
        "prompt_text": "prompt",
        "trace": [{"agent_id": "worker_agent", "output": "bbbb", "usage": None}],
    }
    by_model = {row["model"]: row for row in orchestrator.spend_analytics()["by_model"]}
    assert by_model["model-x"]["usage_source"] == "mixed"
    assert by_model["model-x"]["step_count"] == 2


def test_close_releases_agent_pool_store() -> None:
    """Closing an orchestrator releases a configured durable agent pool."""
    with tempfile.TemporaryDirectory() as directory:
        orchestrator = TaskOrchestrator(
            [ModelAgent("general_agent", "m", tags=("reasoning",))],
            agents_db=str(Path(directory) / "pool.sqlite"),
        )
        assert orchestrator._pool_store is not None
        orchestrator.close()


def test_batch_route_blocks_when_budget_exceeded() -> None:
    """Batch routing fails closed once the configured output budget is spent."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "m", tags=("reasoning", "writing"))],
        budget_max_output_tokens=1,
    )
    orchestrator.run([{"role": "user", "content": "burn through the tiny token budget right now"}])
    with pytest.raises(BudgetExceededError):
        orchestrator.batch_route(["another prompt after the budget is spent"])


def test_batch_route_persists_runs_to_state_store() -> None:
    """Batch routing writes completed runs into an explicitly configured store."""
    with tempfile.TemporaryDirectory() as directory:
        orchestrator = TaskOrchestrator(
            [ModelAgent("general_agent", "m", tags=("reasoning", "writing"))],
            state_db=str(Path(directory) / "state.sqlite"),
        )
        assert orchestrator._store is not None
        records = orchestrator.batch_route(["hello there worker"])
        assert len(records) == 1
        assert len(orchestrator._workflow_runs) == 1
        orchestrator.close()


def _orchestrator() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review")),
        ]
    )


def test_is_trace_complete_rejects_empty_and_malformed_traces() -> None:
    """Trace completeness fails closed for missing or malformed step evidence."""
    orchestrator = _orchestrator()
    assert orchestrator._is_trace_complete({"trace": []}) is False
    assert orchestrator._is_trace_complete({"trace": [{"id": 1}]}) is False
    assert (
        orchestrator._is_trace_complete(
            {"trace": [{"id": 1, "role": "worker", "agent_id": "a", "subtask": "s", "access": "not-a-list", "output": "o"}]}
        )
        is False
    )
    assert (
        orchestrator._is_trace_complete(
            {"trace": [{"id": 1, "role": "worker", "agent_id": "a", "subtask": "s", "access": [], "output": None}]}
        )
        is False
    )


def test_is_policy_safe_run_rejects_conduct_without_required_verification() -> None:
    """Conduct-mode evidence is unsafe when required verification is absent."""
    orchestrator = _orchestrator()
    run = {"mode": "conduct", "policy_snapshot": {"verifier_required": True}, "trace": []}
    assert orchestrator._is_policy_safe_run(run) is False


def test_provider_exclusion_miss_count_counts_unknown_and_excluded_roles() -> None:
    """Provider-exclusion evidence counts unresolved agents and disallowed roles."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("excluded_agent", "m", "mock://a", tags=("reasoning",), provider_exclusions=("worker",))]
    )
    assert orchestrator._provider_exclusion_miss_count({"trace": [{"agent_id": "ghost", "role": "worker"}]}) == 1
    assert orchestrator._provider_exclusion_miss_count({"trace": [{"agent_id": "excluded_agent", "role": "worker"}]}) == 1


def test_security_posture_criterion_fails_on_insecure_profile() -> None:
    """An explicitly insecure server profile is a failed security criterion."""
    orchestrator = _orchestrator()
    criterion = orchestrator._security_posture_criterion(
        {
            "auth_mode": "loopback_no_auth",
            "allow_public_bind": True,
            "expose_trace_by_default": True,
            "rate_limit_requests": 0,
            "max_concurrent_runs": 0,
        }
    )
    assert criterion["status"] == "fail"
    assert "public bind is enabled" in criterion["evidence"]


def test_locale_readiness_criterion_warns_when_keys_missing() -> None:
    """Locale bundles with key drift produce an explicit readiness warning."""
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "m", tags=("reasoning",))])
    analytics = orchestrator.analytics_snapshot(locale_bundles={"en": {"a": "A", "b": "B"}, "ko": {"a": "에이"}})
    criterion = orchestrator._locale_readiness_criterion(analytics)
    assert criterion["status"] == "warn"
    assert "locale key parity" in criterion["evidence"]


def test_provider_egress_criterion_fails_for_insecure_remote_agent() -> None:
    """Plain-HTTP remote provider configuration fails commercial egress posture."""
    orchestrator = TaskOrchestrator([ModelAgent("insecure_agent", "gpt-x", "http://api.example.com/v1")])
    criterion = orchestrator._provider_egress_criterion()
    assert criterion["status"] == "fail"
    assert "insecure_agent" in criterion["evidence"]


def test_freeze_report_cache_value_handles_sets_and_unhashables() -> None:
    """Cache-key normalization is deterministic for sets and unhashable scalars."""
    assert _freeze_report_cache_value({3, 1, 2}) == (1, 2, 3)
    assert _freeze_report_cache_value(bytearray(b"x")) == "bytearray(b'x')"


def test_recommend_config_none_and_over_budget_cheapest() -> None:
    """Recommendation returns None for no candidates and cheapest if none fit."""
    assert _recommend_config([], None) is None
    results = [
        {"name": "quality_config", "quality": 0.9, "cost_usd": 5.0},
        {"name": "budget_config", "quality": 0.5, "cost_usd": 1.0},
    ]
    recommendation = _recommend_config(results, cost_budget_usd=0.5)
    assert recommendation["name"] == "budget_config"
    assert recommendation["reason"] == "no config within budget; cheapest instead"


_INSECURE_PROFILE = {
    "auth_mode": "loopback_no_auth",
    "allow_public_bind": True,
    "expose_trace_by_default": True,
    "rate_limit_requests": 0,
    "max_concurrent_runs": 0,
}

_BLOCKED_REPORTS = [
    ("sales_readiness_report", "readiness_status", "not_ready"),
    ("commercial_readiness_report", "commercial_status", "not_commercial_ready"),
    ("buyer_evidence_manifest_report", "manifest_status", "buyer_review_blocked"),
    ("buyer_handoff_bundle_report", "bundle_status", "buyer_handoff_blocked"),
    ("saleability_decision_report", "saleability_status", "saleability_blocked"),
    ("commercial_evidence_export_report", "export_status", "commercial_export_blocked"),
    ("commercial_acceptance_check_report", "acceptance_status", "commercial_acceptance_blocked"),
    ("commercial_release_candidate_report", "release_status", "commercial_release_blocked"),
    ("commercial_gap_register_report", "gap_register_status", "commercial_gap_register_blocked"),
    ("commercial_procurement_readiness_report", "procurement_status", "commercial_procurement_blocked"),
    ("commercial_contract_readiness_report", "contract_status", "commercial_contract_blocked"),
    ("commercial_onboarding_readiness_report", "onboarding_status", "commercial_onboarding_blocked"),
    ("commercial_operations_readiness_report", "operations_status", "commercial_operations_blocked"),
    ("commercial_security_attestation_report", "security_attestation_status", "commercial_security_attestation_blocked"),
    ("commercial_value_readiness_report", "value_status", "commercial_value_blocked"),
]


def _exercised_orchestrator() -> TaskOrchestrator:
    orchestrator = _orchestrator()
    orchestrator.record_analytics_event(
        "chat_completion_requested",
        {
            "endpoint_path": "/v1/chat/completions",
            "actor_scope": "inference",
            "status_code": 200,
            "duration_ms": 8,
        },
    )
    orchestrator.run(
        [{"role": "user", "content": "Analyze the product, implement it, verify it, and summarize."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this readiness prompt."], mode="route")
    return orchestrator


@pytest.mark.parametrize("method_name,status_field,expected", _BLOCKED_REPORTS)
def test_commercial_reports_classify_blocked_under_insecure_profile(
    method_name: str,
    status_field: str,
    expected: str,
) -> None:
    """Commercial evidence reports expose their blocked state under known risk."""
    orchestrator = _exercised_orchestrator()
    method = getattr(orchestrator, method_name)
    parameters = inspect.signature(method).parameters
    kwargs: dict = {}
    if "locale_bundles" in parameters:
        kwargs["locale_bundles"] = ADMIN_TRANSLATIONS
    if "security_profile" in parameters:
        kwargs["security_profile"] = _INSECURE_PROFILE
    report = method(**kwargs)
    assert report[status_field] == expected
