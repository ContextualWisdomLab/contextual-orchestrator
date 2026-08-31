"""Measured routing evidence: latency ledger, affinity, triage, real-time judge.

Covers the anti-heuristic routing stack (ADR 0034):

- tokens-per-second EWMA in :class:`ModelGroupRouter` with exact Jacobson
  (1988) gain arithmetic and strict input validation;
- cosine-similarity ordering from operator-declared metadata documents;
- the strict ``{"workflow_required": bool}`` triage parser and its
  fail-closed dispatch behavior;
- the real-time fast-mlsirm judge feeding the quality Beta-Bernoulli ledger
  on direct-route paths, including reject failover within the retry budget.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.model_group import (  # noqa: E402
    BETA_PRIOR_FAILURE_COUNT,
    BETA_PRIOR_SUCCESS_COUNT,
    EWMA_LATENCY_GAIN,
    MIN_ROUTING_LATENCY_SECONDS,
    ModelGroupRouter,
)
from contextual_orchestrator.orchestrator import _parse_triage_reply  # noqa: E402


# --- tokens-per-second ledger ------------------------------------------------


def test_tps_ewma_matches_exact_jacobson_arithmetic() -> None:
    router = ModelGroupRouter()
    router.observe_success("member_one", 1.0, output_tokens=100)
    router.observe_success("member_one", 1.0, output_tokens=200)

    first_sample = 100.0 / max(1.0, MIN_ROUTING_LATENCY_SECONDS)
    second_sample = 200.0
    expected = (1 - EWMA_LATENCY_GAIN) * first_sample + EWMA_LATENCY_GAIN * second_sample

    report = router.member_report("member_one")
    assert report["ewma_tokens_per_second"] == pytest.approx(expected, rel=1e-6)


def test_score_remains_successful_responses_per_second_with_token_evidence() -> None:
    fast = ModelGroupRouter()
    slow = ModelGroupRouter()

    for router in (fast, slow):
        router.observe_success("scorer", 0.5, output_tokens=10)

    assert fast.member_score("scorer") == pytest.approx((2.0 / 3.0) / 0.5, rel=1e-9)

    slow.observe_success("scorer", 0.5, output_tokens=30)
    stability_two_successes = (BETA_PRIOR_SUCCESS_COUNT + 2.0) / (
        BETA_PRIOR_SUCCESS_COUNT + 2.0 + BETA_PRIOR_FAILURE_COUNT
    )
    assert slow.member_score("scorer") == pytest.approx(stability_two_successes / 0.5, rel=1e-9)


def test_latency_only_members_keep_responses_per_second_score() -> None:
    router = ModelGroupRouter()
    router.observe_success("latency_only", 0.25)
    alpha = BETA_PRIOR_SUCCESS_COUNT + 1
    beta = BETA_PRIOR_FAILURE_COUNT
    stability = alpha / (alpha + beta)
    assert router.member_score("latency_only") == pytest.approx(stability / 0.25, rel=1e-9)
    report = router.member_report("latency_only")
    assert report["ewma_tokens_per_second"] is None


def test_token_volume_does_not_change_latency_based_order() -> None:
    router = ModelGroupRouter()
    router.observe_success("slow_writer", 1.0, output_tokens=500)
    router.observe_success("fast_writer", 0.5, output_tokens=50)
    ordered = router.ranked_member_ids(["slow_writer", "fast_writer"])
    assert ordered[0] == "fast_writer"


def test_output_tokens_validation_rejects_non_positive_and_boolean() -> None:
    router = ModelGroupRouter()
    for invalid in (0, -5, True, 1.5, "12"):
        with pytest.raises((TypeError, ValueError)):
            router.observe_success("member_one", 1.0, output_tokens=invalid)  # type: ignore[arg-type]


def test_total_tokens_validation_rejects_non_positive_and_boolean() -> None:
    router = ModelGroupRouter()
    for invalid in (0, -5, True, 1.5, "12"):
        with pytest.raises((TypeError, ValueError)):
            router.observe_success("member_one", 1.0, total_tokens=invalid)  # type: ignore[arg-type]


def test_usage_total_tokens_requires_provider_reported_positive_integer() -> None:
    assert TaskOrchestrator._usage_total_tokens({"total_tokens": 42}) == 42
    assert TaskOrchestrator._usage_total_tokens({"total_tokens": 0}) is None
    assert TaskOrchestrator._usage_total_tokens({"total_tokens": True}) is None
    assert TaskOrchestrator._usage_total_tokens({"completion_tokens": 42}) is None


def test_unobserved_member_reports_include_null_token_column() -> None:
    router = ModelGroupRouter()
    report = router.member_report("never_seen")
    assert report["ewma_tokens_per_second"] is None
    assert report["success_posterior_mean"] == pytest.approx(
        BETA_PRIOR_SUCCESS_COUNT / (BETA_PRIOR_SUCCESS_COUNT + BETA_PRIOR_FAILURE_COUNT)
    )


# --- semantic affinity (cosine over declared metadata) ----------------------


def _orch(*agents: ModelAgent) -> TaskOrchestrator:
    return TaskOrchestrator(list(agents))


def test_mock_embedding_vectors_are_deterministic() -> None:
    orchestrator = _orch(ModelAgent("embedding_member", "mock-embed", tags=("embedding",)))
    first = orchestrator._embed_cached("some task text")
    second = orchestrator._embed_cached("some task text")
    assert first is not None and first == second
    assert len(first) == orchestrator.client.MOCK_EMBEDDING_DIMENSION


def test_no_embedding_member_disables_affinity_entirely() -> None:
    agent = ModelAgent("plain_agent", "mock", tags=("reasoning",))
    orchestrator = _orch(agent)
    affinities = orchestrator._semantic_affinities("analyze this repository", [agent])
    assert affinities == {"plain_agent": None}


def test_empty_text_skips_similarity_without_network_calls() -> None:
    agent = ModelAgent("embedding_member", "mock-embed", tags=("embedding",))
    worker = ModelAgent("worker_agent", "mock-worker", tags=("reasoning",), priority=1)
    orchestrator = _orch(agent, worker)
    affinities = orchestrator._semantic_affinities("   ", [agent, worker])
    assert set(affinities.values()) == {None}


def test_cosine_similarity_zero_vector_returns_none() -> None:
    assert TaskOrchestrator._cosine_similarity([0.0, 0.0], [1.0, 1.0]) is None
    assert TaskOrchestrator._cosine_similarity([1.0], [1.0, 1.0]) is None


def test_role_fit_beats_priority_but_not_exclusions() -> None:
    fitting_low = ModelAgent(
        "fitting_agent", "mock-fit", tags=("verification",), priority=1
    )
    mismatched_high = ModelAgent(
        "mismatched_agent", "mock-miss", tags=("coding",), priority=99
    )
    orchestrator = _orch(fitting_low, mismatched_high)
    ranked = orchestrator._ranked_agents("review this patch", "verifier")
    assert ranked[0] is fitting_low

    excluded_fitting = ModelAgent(
        "excluded_fit",
        "mock-excl",
        tags=("verification",),
        priority=50,
        provider_exclusions=("verifier",),
    )
    orchestrator2 = _orch(excluded_fitting, fitting_low)
    ranked2 = orchestrator._ranked_agents.__self__ if False else orchestrator2._ranked_agents(
        "review this patch", "verifier"
    )
    assert ranked2[0] is fitting_low  # exclusion always trails eligibility


def test_measured_affinity_precedes_missing_affinity_in_same_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measured = ModelAgent("measured_agent", "mock", tags=("reasoning",))
    missing = ModelAgent("missing_agent", "mock", tags=("reasoning",))
    orchestrator = _orch(missing, measured)
    monkeypatch.setattr(
        orchestrator,
        "_semantic_affinities",
        lambda *_: {"missing_agent": None, "measured_agent": 0.1},
    )
    assert orchestrator._ranked_agents("task", "worker")[0] is measured


def test_chat_ranking_excludes_non_chat_models_but_capability_routing_keeps_them() -> None:
    chat = ModelAgent("chat_agent", "mock-chat", tags=("reasoning",))
    embedding = ModelAgent("embedding_agent", "mock-embed", tags=("embedding",))
    orchestrator = _orch(embedding, chat)
    assert orchestrator._ranked_agents("task", "worker") == [chat]
    assert orchestrator._capability_agents("embedding", None) == [embedding]


# --- structured triage -------------------------------------------------------


def test_triage_parser_accepts_exact_schema_only() -> None:
    assert _parse_triage_reply('{"workflow_required": true}') is True
    assert _parse_triage_reply('{"workflow_required": false}') is False


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "not json",
        '{"workflow_required": true, "extra": 1}',
        '{"workflow_required": "true"}',
        '{"workflow_required": false, "workflow_required": false}',
        '{"other": true}',
        '["workflow_required"]',
    ],
)
def test_triage_parser_rejects_every_violation(reply: str) -> None:
    with pytest.raises(ValueError):
        _parse_triage_reply(reply)


def test_triage_failure_fails_closed_to_conduct() -> None:
    class ExplodingClient(ModelClient):  # type: ignore[misc]
        def chat(self, agent, messages, temperature: float = 0.2) -> str:  # type: ignore[override]
            raise RuntimeError("triage transport down")

    orchestrator = _orch(ModelAgent("general_agent", "mock", tags=("reasoning",)))
    orchestrator.client = ExplodingClient()
    assert orchestrator._needs_workflow("anything at all") is True


def test_triage_verdicts_are_cached_by_content_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    orchestrator = _orch(ModelAgent("general_agent", "mock", tags=("reasoning",)))

    def counting_compute(text: str) -> bool:
        calls.append(text)
        return False

    monkeypatch.setattr(orchestrator, "_compute_triage_verdict", counting_compute)
    assert orchestrator._needs_workflow("same text") is False
    assert orchestrator._needs_workflow("same text") is False
    assert calls == ["same text"]  # second decision served from the verdict cache


def test_triage_with_no_agents_degrades_to_direct_route() -> None:
    orchestrator = _orch(ModelAgent("general_agent", "mock"))
    orchestrator.agents = []
    assert orchestrator._compute_triage_verdict("text") is False


# --- real-time judge on route paths -----------------------------------------


class _VerdictJudgeAdapter:
    """Minimal stand-in capturing that the judge seam was invoked."""

    def __init__(self, accepted: bool) -> None:
        self.accepted = accepted
        self.calls: list[str] = []

    def __call__(self, *, task: str, answer: str, criteria: tuple) -> object:
        self.calls.append(answer)

        class _Result:
            accepted = self.accepted
            rationale = "stub verdict"
            usage = None
            orchestration_mode = "route"

        return _Result()


def test_realtime_judge_accept_records_quality_success(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = _orch(ModelAgent("worker_agent", "mock", tags=("reasoning",)))

    monkeypatch.setattr(orchestrator, "_model_judge_verification", lambda *a, **k: {
        "accepted": True, "reason": "stub verdict", "verifier_output": k.get("answer", ""),
        "judge": "model",
    })
    verification = orchestrator._realtime_route_judge(
        text="task", answer="good answer", served_id="worker_agent",
        latency_seconds=0.4, usage={"completion_tokens": 42}, free_only=False,
    )
    assert verification["accepted"] is True
    quality = orchestrator._quality_router.member_report("worker_agent")
    assert quality["success_count"] == 1
    assert quality["ewma_tokens_per_second"] == pytest.approx(42 / max(0.4, MIN_ROUTING_LATENCY_SECONDS))


def test_realtime_judge_reject_records_quality_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = _orch(ModelAgent("worker_agent", "mock", tags=("reasoning",)))
    monkeypatch.setattr(orchestrator, "_model_judge_verification", lambda *a, **k: {
        "accepted": False, "reason": "insufficient evidence", "verifier_output": "",
        "judge": "model",
    })
    verification = orchestrator._realtime_route_judge(
        text="task", answer="bad answer", served_id="worker_agent",
        latency_seconds=0.2, usage=None, free_only=False,
    )
    assert verification["accepted"] is False
    quality = orchestrator._quality_router.member_report("worker_agent")
    assert quality["failure_count"] == 1


def test_route_once_failover_after_judge_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning",), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning",), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents)

    def fake_invoke(primary, messages, **kwargs):
        if primary.id == "primary_worker":
            return "weak answer", "primary_worker", {"completion_tokens": 10}
        return "strong answer", "backup_worker", None

    monkeypatch.setattr(orchestrator, "_invoke", fake_invoke)

    def judge(text, fallback, *, free_only=False, deadline=None):
        del deadline
        accepted = "strong" in fallback["verifier_output"]
        return {
            "accepted": accepted,
            "reason": "verdict",
            "verifier_output": fallback["verifier_output"],
            "judge": "model",
        }

    monkeypatch.setattr(orchestrator, "_model_judge_verification", judge)
    result = orchestrator.route_once([{"role": "user", "content": "do work"}])
    assert result["answer"] == "strong answer"
    assert result["trace"][-1]["agent_id"] == "backup_worker"
    assert result["verification"]["accepted"] is True
    primary_quality = orchestrator._quality_router.member_report("primary_worker")
    backup_quality = orchestrator._quality_router.member_report("backup_worker")
    assert primary_quality["failure_count"] == 1
    assert backup_quality["success_count"] == 1


def test_route_once_deadline_stops_judge_driven_failover_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tight ``deadline_seconds`` also blocks route_once's own next-candidate retry.

    ``route_once``'s outer loop (distinct from ``_invoke``'s cross-candidate
    failover) only advances to a second ranked candidate when the first's
    answer comes back successfully but the real-time judge rejects it (see
    ``test_route_once_failover_after_judge_reject`` above). A deadline must
    stop that judge-driven retry too, not only a transport-failure retry.
    """
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning",), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning",), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents, tool_retry_attempts=1)
    calls: list[str] = []

    def slow_fake_invoke(primary, messages, **kwargs):
        calls.append(primary.id)
        time.sleep(0.08)
        return "weak answer", primary.id, None

    monkeypatch.setattr(orchestrator, "_invoke", slow_fake_invoke)
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda *a, **k: {
            "accepted": False,
            "reason": "always reject",
            "verifier_output": "",
            "judge": "model",
        },
    )

    with pytest.raises(RuntimeError, match="request deadline exceeded"):
        orchestrator.route_once(
            [{"role": "user", "content": "do work"}],
            deadline_seconds=0.05,
        )

    # Without the deadline, the always-rejecting judge would make route_once
    # try both ranked candidates (max_attempts = 1 + min(1, MAX_TOOL_RETRY_ATTEMPTS) = 2).
    # The 0.05s deadline, shorter than one 0.08s call, must cut this off
    # after only the first.
    assert calls == ["primary_worker"]


def test_route_once_deadline_is_propagated_to_slow_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("primary_worker", "mock", tags=("reasoning",), priority=5)]
    )

    def deadline_aware_judge(text, fallback, *, free_only=False, deadline=None):
        del text, fallback, free_only
        assert deadline is not None
        time.sleep(max(0.0, deadline - time.monotonic()))
        raise TimeoutError("judge deadline exceeded")

    monkeypatch.setattr(orchestrator, "_model_judge_verification", deadline_aware_judge)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="judge deadline exceeded"):
        orchestrator.route_once(
            [{"role": "user", "content": "do work"}], deadline_seconds=0.04
        )
    assert time.monotonic() - started < 0.12


def test_policy_realtime_judge_must_be_boolean() -> None:
    from contextual_orchestrator.orchestrator import OrchestrationPolicy

    with pytest.raises(ValueError):
        OrchestrationPolicy(realtime_judge="yes")  # type: ignore[arg-type]


def test_disabled_realtime_judge_keeps_legacy_verification_shape() -> None:
    orchestrator = _orch(ModelAgent("worker_agent", "mock", tags=("reasoning",)))
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    verification = orchestrator._realtime_route_judge(
        text="task", answer="answer text", served_id="worker_agent",
        latency_seconds=0.3, usage=None, free_only=False,
    )
    assert verification == {
        "accepted": True,
        "reason": "single route path",
        "verifier_output": "answer text",
        "judge": "model",
    }
    quality = orchestrator._quality_router.member_report("worker_agent")
    assert quality["success_count"] == 0
    assert orchestrator._quality_router.member_observation_count("worker_agent") == 0


def test_admin_state_exposes_both_routing_ledgers() -> None:
    orchestrator = _orch(ModelAgent("worker_agent", "mock", tags=("reasoning",)))
    orchestrator._quality_router.observe_success("worker_agent", 0.5, output_tokens=25)
    evidence = orchestrator.admin_state()["routing_evidence"]
    assert set(evidence) == {"transport", "quality"}
    assert evidence["quality"]["worker_agent"]["ewma_tokens_per_second"] == pytest.approx(50.0)
    assert evidence["transport"]["worker_agent"]["ewma_tokens_per_second"] is None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))


def test_observation_count_is_zero_for_unknown_member() -> None:
    router = ModelGroupRouter()
    assert router.member_observation_count("ghost_member") == 0
    router.observe_failure("known_member")
    assert router.member_observation_count("known_member") == 1
