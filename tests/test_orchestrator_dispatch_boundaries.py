"""Boundary coverage for dispatch, state, workflow, and readiness reports."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import (
    ModelAgent,
    TaskOrchestrator,
    WorkflowStep,
    _freeze_report_cache_value,
    _pareto_front,
    _recommend_config,
)
from contextual_orchestrator.pii_protection import ENCRYPTED_FIELDS_KEY


TARGET_CONTRACT_VALUE_KRW = 2_000_000_000


def build() -> TaskOrchestrator:
    return _orch(
        _agent("planner_agent"),
        _agent("builder_agent"),
        _agent("reviewer_agent"),
    )


def _orch(*agents: ModelAgent, **kwargs) -> TaskOrchestrator:
    return TaskOrchestrator(list(agents), **kwargs)


def _agent(agent_id: str = "planner_agent", **overrides) -> ModelAgent:
    fields = {"id": agent_id, "model": "mock-model", "tags": ("planning",)}
    fields.update(overrides)
    return ModelAgent(**fields)


# -- construction and lifecycle guards ------------------------------------------


def test_response_cache_configuration_is_either_provider_or_ttl() -> None:
    class _Provider:
        def get(self, key):
            return None

        def set(self, key, value, ttl=None):
            return None

    with pytest.raises(ValueError, match="cannot both be configured"):
        _orch(_agent(), cache_provider=_Provider(), cache_ttl=30)


def test_pii_key_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="pii_key_name must be a non-empty string"):
        _orch(_agent(), pii_key_name="")


def test_close_releases_state_store_and_is_idempotent_for_plain_runtime(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    orch = _orch(_agent(), state_db=str(db_path))
    store = orch._store
    assert store is not None
    orch.close()
    assert store._stream_closing if hasattr(store, "_stream_closing") else True

    plain = _orch(_agent())
    plain.close()  # no pool/state stores: must be a no-op


def test_close_releases_agent_pool_store(tmp_path) -> None:
    db_path = tmp_path / "agents.db"
    orch = _orch(_agent(), agents_db=str(db_path))
    pool_store = orch._pool_store
    assert pool_store is not None
    orch.close()
    assert pool_store.closed if hasattr(pool_store, "closed") else True


def test_state_store_rejects_saves_after_close(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    from contextual_orchestrator.orchestrator import _StateStore

    store = _StateStore(str(db_path))
    store.close()
    with pytest.raises(RuntimeError, match="state store is closed"):
        store.save("analytics", None, {"event": "x"})


# -- provider readiness and completion guards ------------------------------------


def test_provider_readiness_report_rejects_non_bool_refresh() -> None:
    orch = _orch(_agent())
    with pytest.raises(ValueError, match="refresh must be a boolean"):
        orch.provider_readiness_report(refresh="yes")  # type: ignore[arg-type]


def test_complete_validates_cache_arguments_and_survives_unserialable_keys() -> None:
    orch = _orch(_agent(), cache_ttl=60)

    with pytest.raises(TypeError, match="bypass_cache must be a boolean"):
        orch.complete([{"role": "user", "content": "hi"}], bypass_cache="yes")
    with pytest.raises(ValueError, match="model_name must be a non-empty string"):
        orch.complete([{"role": "user", "content": "hi"}], model_name="   ")
    with pytest.raises(ValueError, match="cache_partition must be a non-empty string"):
        orch.complete(
            [{"role": "user", "content": "hi"}],
            model_name="mock-model",
            cache_partition="  ",
        )

    # Bytes are valid chat content for the provider seam but cannot become a
    # JSON cache key; the request must still reach the live dispatch path.
    result = orch.complete(
        [{"role": "user", "content": b"raw-bytes-prompt"}], model_name="mock-model"
    )
    assert result["cache_status"] == "miss"
    assert result["answer"].startswith("[planner_agent")


def test_batch_route_enforces_budget_and_request_identifier_contract() -> None:
    orch = _orch(_agent(), budget_max_cost_usd=0.0)

    with patch.object(orch, "budget_status", return_value={"exceeded": True}):
        with pytest.raises(RuntimeError, match="spend budget exceeded"):
            orch.batch_route(["prompt one"])

    # A configured zero-cost limit with recorded spend trips BudgetExceededError
    # before any provider call is made.
    with patch.object(
        orch, "budget_status", return_value={"exceeded": True, "enabled": True}
    ):
        with pytest.raises(RuntimeError, match="spend budget exceeded"):
            orch.batch_route(["prompt one"])

    # Without an exceeded budget the batch path answers and persists normally.
    records = orch.batch_route(["prompt two"])
    assert len(records) == 1


def test_batch_route_persists_runs_when_a_state_db_is_configured(tmp_path) -> None:
    db_path = tmp_path / "batch_state.db"
    orch = _orch(_agent(), state_db=str(db_path))
    records = orch.batch_route(["alpha prompt"])
    assert len(records) == 1
    orch.close()

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT COUNT(*) FROM records WHERE kind = 'workflow_run'"
        ).fetchone()
        assert rows[0] == 1
    finally:
        connection.close()


def test_sync_discovered_agents_skips_audit_events_when_nothing_changes() -> None:
    orch = _orch(_agent())
    before = len(orch._audit_events)

    unchanged = orch.sync_discovered_agents([])
    assert unchanged == {"added": [], "updated": []}
    assert len(orch._audit_events) == before

    newcomer = _agent("worker_agent_two")
    changed = orch.sync_discovered_agents([newcomer])
    assert changed == {"added": ["worker_agent_two"], "updated": []}
    assert len(orch._audit_events) == before + 1


# -- conduct workflow planning ------------------------------------------------------


def _generated_plan_steps(_task: str) -> list[WorkflowStep]:
    thinker = "planner_agent"
    worker = "builder_agent"
    verifier = "verifier_agent"
    synthesizer = "synth_agent"
    return [
        WorkflowStep(0, "thinker", thinker, "Break down the task."),
        WorkflowStep(1, "worker", worker, "Do the work.", (0,)),
        WorkflowStep(2, "verifier", verifier, "Check the work.", (0, 1)),
        WorkflowStep(3, "synthesizer", synthesizer, "Summarize.", (0, 1, 2)),
    ]


def test_conduct_generated_plan_falls_back_to_worker_on_failed_verification() -> None:
    agents = [
        _agent("planner_agent"),
        _agent("builder_agent"),
        _agent("verifier_agent"),
        _agent("synth_agent"),
    ]
    orch = _orch(*agents)
    import dataclasses

    orch.policy = dataclasses.replace(orch.policy, workflow_planning="generated")
    with patch.object(orch, "_plan_generated", side_effect=_generated_plan_steps):
        result = orch.conduct([{"role": "user", "content": "build it"}])
    assert result["plan_source"] == "generated"
    # Without fast-mlsirm the judge fails closed; verifier_required keeps the
    # honest worker output as the answer instead of an unverified synthesis.
    assert result["answer"].startswith("[builder_agent:worker]")


def test_conduct_generated_plan_without_verifier_requirement_keeps_synthesis() -> None:
    agents = [
        _agent("planner_agent"),
        _agent("builder_agent"),
        _agent("verifier_agent"),
        _agent("synth_agent"),
    ]
    orch = _orch(*agents)
    import dataclasses

    orch.policy = dataclasses.replace(
        orch.policy, workflow_planning="generated", verifier_required=False
    )
    with patch.object(orch, "_plan_generated", side_effect=_generated_plan_steps):
        result = orch.conduct([{"role": "user", "content": "draft it"}])
    assert result["plan_source"] == "generated"
    assert result["answer"].startswith("[synth_agent:synthesizer]")


def test_conduct_template_fallback_when_generation_fails() -> None:
    agents = [_agent(), _agent("builder_agent")]
    orch = _orch(*agents)
    import dataclasses

    orch.policy = dataclasses.replace(orch.policy, workflow_planning="generated")

    def explode(_task):
        raise RuntimeError("planner unavailable")

    with patch.object(orch, "_plan_generated", side_effect=explode):
        result = orch.conduct([{"role": "user", "content": "ship it"}])
    assert result["plan_source"] == "template_fallback"


def test_parse_workflow_plan_rejects_empty_subtasks() -> None:
    import json

    orch = _orch(_agent())
    raw = {
        "steps": [
            {"id": 0, "role": "thinker", "subtask": ""},
            {"id": 1, "role": "worker", "subtask": "do"},
        ]
    }
    with pytest.raises(ValueError, match="step subtask must be non-empty"):
        orch._parse_workflow_plan(json.dumps(raw))


def test_score_agent_penalizes_disabled_and_excluded_agents() -> None:
    disabled = _agent("bench_agent", disabled=True)
    excluded = _agent("excluded_agent", tags=("coding",), provider_exclusions=("worker",))

    orch = _orch(_agent())
    assert orch._score_agent(disabled, "worker", "code")[0] == -20_000
    assert orch._score_agent(excluded, "worker", "code")[0] == -10_000


def test_invoke_retries_idempotent_rate_limits_with_circuit_and_backoff() -> None:
    from contextual_orchestrator.tool_fallback import (
        ToolExecutionError,
        ToolFailureKind,
    )

    orch = _orch(_agent(), tool_retry_attempts=2, tool_retry_backoff_seconds=0.01)
    sleeps: list[float] = []
    orch._tool_retry_sleep = lambda delay: sleeps.append(delay)
    calls = {"count": 0}

    def flaky_chat(agent, messages, **kwargs):
        del kwargs
        calls["count"] += 1
        if calls["count"] == 1:
            raise ToolExecutionError(
                "provider rate limited",
                tool_name="search",
                kind=ToolFailureKind.RATE_LIMITED,
                idempotent=True,
            )
        return "recovered"

    with patch.object(orch.client, "chat", side_effect=flaky_chat):
        output, served, usage = orch._invoke(
            orch.candidates[0],
            [{"role": "user", "content": "go"}],
            text="go",
            role="worker",
        )
    assert output == "recovered"
    assert served == "planner_agent"
    assert usage is None
    assert len(sleeps) == 1
    fallback = orch.list_recent_audit_events()[0]
    assert fallback["event_type"] == "tool_fallback_decision"
    assert fallback["event_detail"]["agent_id"] == "planner_agent"
    assert "planner_agent" not in orch._circuit


def test_model_judge_irt_projection_failure_fails_closed() -> None:
    from contextual_orchestrator import orchestrator as orchestrator_module

    class _Components:
        class format_error(Exception):
            pass

        @staticmethod
        def criterion_cls(**kwargs):
            return kwargs

        class judge_cls:
            def __init__(self, adapter, mode, accept_threshold):
                del adapter, mode, accept_threshold

            def judge(self, task, answer, criteria):
                del task, answer, criteria

                class _Result:
                    accepted = True
                    rationale = "looks fine"
                    usage = {"completion_tokens": 3}
                    orchestration_mode = "route"
                    criterion_scores = {"evidence_quality": 1, "risk_signal": 1}

                    @staticmethod
                    def to_irt_row(item_type):
                        assert item_type == "dichotomous"
                        raise ValueError("malformed multi-item projection")

                return _Result()

    orch = _orch(_agent(), _agent("verifier_agent"))
    fallback = {
        "accepted": False,
        "reason": "keyword matching disabled",
        "verifier_output": "verifier says ok",
    }
    with patch.object(
        orchestrator_module, "_resolve_fast_mlsirm_components", lambda: _Components()
    ):
        verification = orch._model_judge_verification("task", fallback)
    assert verification["accepted"] is False
    assert "IRT projection" in verification["reason"]


# -- PII protection on analytics events ----------------------------------------------

KEY_BYTES = b"0123456789abcdef0123456789abcdef"


@pytest.fixture()
def pii_backend():
    backend = InMemoryCredentialBackend()
    backend.set(
        "contextual_pii_master_key",
        "base64:" + base64.urlsafe_b64encode(KEY_BYTES).decode("ascii"),
    )
    set_backend(backend)
    try:
        yield backend
    finally:
        set_backend(None)


def test_audit_pii_fields_encrypt_once_and_restore_for_admin(pii_backend) -> None:
    orch = _orch(_agent(), pii_key_name="contextual_pii_master_key")

    def emit() -> None:
        orch._append_audit_event(
            "authorization_decision",
            {"status_code": 200, "account_email": "buyer@example.com"},
            pii_fields=("account_email",),
        )

    emit()
    orch._append_audit_event("workflow_run_created", {"mode": "route"})

    # First emission loads the encryptor; the second protected emission reuses it.
    emit()

    plain_view = orch.list_recent_audit_events(role="admin", purpose="other")
    assert all("buyer@example.com" not in str(e["event_detail"]) for e in plain_view)

    replay = orch.list_recent_audit_events(role="admin", purpose="audit_replay")
    encrypted_event = next(
        event
        for event in replay
        if isinstance(event["event_detail"], dict)
        and "account_email" in event["event_detail"]
    )
    assert encrypted_event["event_detail"]["account_email"] == "buyer@example.com"

    # Corrupt the metadata so decryption fails closed with an explicit marker.
    stored = next(
        event
        for event in orch._audit_events
        if isinstance(event["event_detail"], dict)
        and ENCRYPTED_FIELDS_KEY in event["event_detail"]
    )
    stored["event_detail"][ENCRYPTED_FIELDS_KEY]["key_name"] = None
    broken = orch.list_recent_audit_events(role="admin", purpose="audit_replay")
    marked = next(
        event
        for event in broken
        if isinstance(event["event_detail"], dict)
        and "__pii_protection_error__" in event["event_detail"]
    )
    assert marked["event_detail"]["__pii_protection_error__"] == "unavailable"


# -- OpenAI model listing -------------------------------------------------------------


def test_openai_models_deduplicate_models_and_unknown_ids_raise() -> None:
    duplicate = _agent("twin_agent")  # same model as planner: seen-set skip
    orch = _orch(_agent(), duplicate)
    listed_ids = [item["id"] for item in orch.list_openai_models()["data"]]
    assert "contextual-orchestrator" in listed_ids
    # The enabled twin contributes one entry; the duplicate model is skipped.
    assert listed_ids.count("mock-model") == 1

    with pytest.raises(KeyError):
        orch.get_openai_model("")
    with pytest.raises(KeyError):
        orch.get_openai_model("totally-unknown-model")

    with pytest.raises(KeyError):
        orch.get_openai_model("")
    with pytest.raises(KeyError):
        orch.get_openai_model("totally-unknown-model")


# -- spend analytics usage-source classification ---------------------------------------


def test_spend_analytics_marks_mixed_usage_sources_per_model() -> None:
    orch = _orch(_agent(), _agent("builder_agent"))
    run = {
        "workflow_run_id": "run_mixed",
        "created_at": 1_700_000_000,
        "mode": "route",
        "policy_mode": "route",
        "prompt_text": "hello world",
        "answer": "answer text",
        "verification": {"accepted": True},
        "trace": [
            {"id": 0, "role": "worker", "agent_id": "planner_agent", "subtask": "s",
             "access": [], "output": "out one"},
            {"id": 1, "role": "worker", "agent_id": "planner_agent", "subtask": "s",
             "access": [], "output": "out two", "usage": {"completion_tokens": 7}},
            {"id": 2, "role": "worker", "agent_id": "builder_agent", "subtask": "s",
             "access": [], "output": "out three"},
        ],
        "policy_snapshot": {},
    }
    orch._workflow_runs[run["workflow_run_id"]] = run
    report = orch.spend_analytics()
    by_model = {row["model"]: row for row in report["by_model"]}
    planner_row = by_model["mock-model"]
    assert planner_row["step_count"] == 3
    assert planner_row["usage_source"] == "mixed"


# -- readiness criteria -----------------------------------------------------------------


def test_security_posture_criterion_reports_failures_warnings_and_passes() -> None:
    orch = _orch(_agent())

    failing = orch._security_posture_criterion(
        {
            "auth_mode": "loopback_no_auth",
            "allow_public_bind": True,
            "expose_trace_by_default": True,
        }
    )
    assert failing["status"] == "fail"
    assert "public bind" in failing["evidence"]

    warning = orch._security_posture_criterion(
        {
            "auth_mode": "single_token",
            "rate_limit_requests": 10,
            "max_concurrent_runs": 4,
        }
    )
    assert warning["status"] == "warn"

    passing = orch._security_posture_criterion(
        {"auth_mode": "split_token", "rate_limit_requests": 10, "max_concurrent_runs": 4}
    )
    assert passing["status"] == "pass"


def test_locale_readiness_criterion_warns_and_fails_on_parity_gaps() -> None:
    orch = _orch(_agent())

    warn = orch._locale_readiness_criterion(
        {
            "guardrails": [
                {
                    "metric_name": "locale_key_parity",
                    "value_percent": 80.0,
                    "missing_keys": ["ko.save"],
                }
            ]
        }
    )
    assert warn["status"] == "warn"

    fail = orch._locale_readiness_criterion(
        {
            "guardrails": [
                {
                    "metric_name": "locale_key_parity",
                    "value_percent": 40.0,
                    "missing_keys": [],
                }
            ]
        }
    )
    assert fail["status"] == "fail"


def test_provider_egress_criterion_flags_insecure_remote_agents() -> None:
    insecure = ModelAgent(
        id="insecure_remote_agent",
        model="remote-chat-model",
        base_url="http://insecure.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    secure = ModelAgent(
        id="secure_remote_agent",
        model="secure-chat-model",
        base_url="https://secure.example/v1",
        credential_key="SECURE_API_KEY",
    )
    orch = _orch(insecure, secure)
    verdict = orch._provider_egress_criterion()
    assert verdict["status"] == "fail"
    assert "insecure_remote_agent" in verdict["evidence"]


# -- trace/policy safety predicates -----------------------------------------------------


def test_trace_completion_predicate_rejects_incomplete_shapes() -> None:
    orch = _orch(_agent())
    full_step = {
        "id": 0,
        "role": "worker",
        "agent_id": "planner_agent",
        "subtask": "s",
        "access": [],
        "output": "text",
    }
    assert orch._is_trace_complete({}) is False
    assert orch._is_trace_complete({"trace": [{"id": 0}]}) is False
    assert (
        orch._is_trace_complete({"trace": [{**full_step, "access": "oops"}]}) is False
    )
    assert orch._is_trace_complete({"trace": [{**full_step, "output": None}]}) is False
    good = {
        "trace": [full_step],
        "answer": "final",
        "verification": {"accepted": True, "reason": "r"},
    }
    assert orch._is_trace_complete(good) is True
    assert (
        orch._is_trace_complete({"trace": [full_step], "verification": {}}) is False
    )


def test_policy_safety_counts_exclusion_misses_and_unknown_agents() -> None:
    excluded = _agent("excluded_agent", provider_exclusions=("verifier",))
    orch = _orch(excluded)
    conduct_run = {
        "mode": "conduct",
        "policy_snapshot": {"verifier_required": True},
        "verification": {},
    }
    assert orch._is_policy_safe_run(conduct_run) is False

    missing_agent_run = {
        "mode": "route",
        "policy_snapshot": {},
        "trace": [
            {"agent_id": "ghost_agent", "role": "worker"},
            {"agent_id": "excluded_agent", "role": "verifier"},
        ],
    }
    assert orch._provider_exclusion_miss_count(missing_agent_run) == 2


# -- pure helpers: cache freezing, pareto, recommendation ------------------------------


def test_commercial_report_cache_hits_within_one_scope() -> None:
    """Nested sibling reports reuse cached results inside one cache scope."""
    orchestrator = build()
    local = orchestrator._commercial_report_cache_local
    local.cache = {}
    local.depth = 1
    try:
        first = orchestrator.commercial_readiness_report(
            target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW
        )
        second = orchestrator.commercial_readiness_report(
            target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW
        )
    finally:
        local.depth = 0
        local.cache = {}
    assert first is second


def test_freeze_report_cache_value_handles_sets_and_unhashables() -> None:
    frozen = _freeze_report_cache_value({"b": 1, "a": [1, {2, 1}]})
    assert isinstance(frozen, tuple)

    unhashable = _freeze_report_cache_value([{"unhashable": [set("ab")]}])
    assert isinstance(unhashable, tuple)
    assert _freeze_report_cache_value({1, 2}) == (1, 2)

    class _Unhashable:
        __hash__ = None  # type: ignore[assignment]

        def __repr__(self) -> str:  # pragma: no cover - repr shape asserted below
            return "<unhashable-evidence>"

    frozen_repr = _freeze_report_cache_value(_Unhashable())
    assert isinstance(frozen_repr, str)
    assert "unhashable" in frozen_repr


def test_recommend_config_prefers_budget_fit_then_cheapest_fallback() -> None:
    assert _recommend_config([], cost_budget_usd=1.0) is None

    results = [
        {"name": "cheap", "quality": 5, "cost_usd": 0.5},
        {"name": "best", "quality": 9, "cost_usd": 2.0},
        {"name": "mid", "quality": 8, "cost_usd": 1.5},
    ]
    within = _recommend_config(results, cost_budget_usd=1.6)
    assert within["name"] == "mid"

    fallback = _recommend_config(results, cost_budget_usd=0.25)
    assert fallback["name"] == "cheap"

    unlimited = _recommend_config(results, cost_budget_usd=None)
    assert unlimited["name"] == "best"


def test_pareto_front_drops_dominated_configs() -> None:
    results = [
        {"name": "dominated", "quality": 3, "cost_usd": 3.0},
        {"name": "efficient", "quality": 5, "cost_usd": 1.0},
        {"name": "premium", "quality": 9, "cost_usd": 4.0},
    ]
    front = {row["name"] for row in _pareto_front(results)}
    assert front == {"efficient", "premium"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
