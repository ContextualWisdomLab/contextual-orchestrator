"""Fast-MLSIRM contextual ability ordering for cold start and failover."""

from __future__ import annotations

import math
import numpy as np
from pathlib import Path
import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.psychometric_routing import PsychometricRoutingEvidence
from scripts.benchmark_psychometric_routing import _require_runtime
from scripts.benchmark_psychometric_heldout import _expected_brier


def test_psychometric_benchmark_requires_python_312() -> None:
    try:
        _require_runtime((3, 11))
    except SystemExit as error:
        assert "uv run --python 3.12" in str(error)
    else:
        raise AssertionError("Python 3.11 must not enter the benchmark dependency path")

    _require_runtime((3, 12))


def test_expected_brier_includes_bernoulli_outcome_variance() -> None:
    assert _expected_brier(0.5, 0.5) == 0.25
    assert _expected_brier(1.0, 0.5) == 0.5


def test_fast_mlsirm_fit_uses_judge_acceptance_item_for_context_score(monkeypatch) -> None:
    """Criterion IRT rows inform one MLSRM fit; acceptance remains the route score."""
    import fast_mlsirm

    captured: dict[str, object] = {}

    class Result:
        convergence_status = "converged"
        params = object()
        model = "MLSRM"

    def fake_fit_experiment(fit_callable, responses, item_type, **kwargs):
        captured.update(item_type=item_type, responses=responses.copy(), config=kwargs["config"])
        return Result()

    def fake_predict(_params, factor_id, *, model):
        del model
        probabilities = np.full((5, len(factor_id)), 0.5)
        probabilities[:, 0] = [0.1, 0.9, 0.3, 0.4, 0.2]
        return probabilities

    monkeypatch.setattr(fast_mlsirm, "fit_irt_experiment", fake_fit_experiment)
    monkeypatch.setattr(fast_mlsirm, "predict_proba", fake_predict)
    evidence = PsychometricRoutingEvidence()
    contexts = ("system-a/user-a", "system-b/user-b")
    agents = [f"model_{index}" for index in range(5)]
    for context_index, context in enumerate(contexts):
        for agent_index, agent_id in enumerate(agents):
            accepted = (agent_index + context_index) % 2 == 0
            evidence.observe(
                context,
                agent_id,
                accepted,
                [float(context_index + 1), 1.0],
                irt_row=(int(accepted), int(not accepted)),
            )

    ranked = evidence.ranked_evidence(agents, contexts[0], [1.0, 1.0])

    assert captured["item_type"] == "dichotomous"
    assert captured["config"].model == "MLSRM"  # type: ignore[union-attr]
    assert np.asarray(captured["responses"]).shape == (5, 6)
    assert ranked[0][0] == "model_1"


def test_contextual_fast_mlsirm_evidence_precedes_static_coldstart_order(monkeypatch) -> None:
    """Initial selection uses contextual ability before operator/static fallback."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("static_first", "model-a", priority=100),
            ModelAgent("quality_first", "model-b", priority=1),
            ModelAgent("unmeasured_agent", "model-c", priority=50),
        ]
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [
            (next(agent_id for agent_id in agent_ids if agent_id.startswith("quality_first:")), 0.91)
        ],
    )
    monkeypatch.setattr(orchestrator._psychometric_router, "has_observations", lambda: True)

    ranked = orchestrator._ranked_agents(
        "user request", "worker", prompt_context='[{"role":"system","content":"policy"}]'
    )

    assert [agent.id for agent in ranked] == [
        "quality_first",
        "static_first",
        "unmeasured_agent",
    ]


def test_contextual_evidence_never_promotes_a_role_excluded_agent(monkeypatch) -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("eligible_agent", "model-a", priority=1),
            ModelAgent(
                "excluded_agent",
                "model-b",
                priority=100,
                provider_exclusions=("worker",),
            ),
        ]
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router, "has_observations", lambda: True
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [(agent_ids[-1], 0.99)],
    )

    ranked = orchestrator._ranked_agents(
        "request", "worker", prompt_context="system/user"
    )

    assert [agent.id for agent in ranked] == ["eligible_agent", "excluded_agent"]


def test_contextual_fast_mlsirm_evidence_orders_every_post_413_candidate(monkeypatch) -> None:
    """After the rejected primary, evidenced candidates lead unmeasured fallbacks."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("primary_agent", "model-a", priority=100),
            ModelAgent("static_backup", "model-b", priority=90),
            ModelAgent("quality_backup", "model-c", priority=1),
        ]
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [
            (next(agent_id for agent_id in agent_ids if agent_id.startswith("quality_backup:")), 0.88)
        ],
    )
    monkeypatch.setattr(orchestrator._psychometric_router, "has_observations", lambda: True)

    ranked = orchestrator._failover_candidates(
        orchestrator._agent("primary_agent"),
        "user request",
        "worker",
        allowed_agent_ids={"primary_agent", "static_backup", "quality_backup"},
        prompt_context="system/user interaction",
    )

    assert [agent.id for agent in ranked] == [
        "primary_agent",
        "quality_backup",
        "static_backup",
    ]


def test_contextual_judge_observation_survives_restart_without_raw_prompt(
    tmp_path: Path,
) -> None:
    state_db = str(tmp_path / "state.sqlite3")
    agents = [ModelAgent("model_a", "model-a")]
    first = TaskOrchestrator(agents, state_db=state_db)
    first._observe_contextual_quality(
        "system secret/user request",
        "model_a",
        accepted=True,
        latency_seconds=0.1,
        output_tokens=10,
        irt_row=(1, 0),
    )
    first.close()

    second = TaskOrchestrator(agents, state_db=state_db)
    records = second._psychometric_router.records()
    second.close()

    candidate_id = TaskOrchestrator._psychometric_candidate_id(agents[0])
    assert records == [
        {
            "context_id": PsychometricRoutingEvidence.context_id(
                "system secret/user request"
            ),
            "agent_id": candidate_id,
            "accepted": True,
            "irt_row": [1, 0],
            "vector": None,
        }
    ]
    assert "system secret" not in Path(state_db).read_bytes().decode(
        "utf-8", errors="ignore"
    )


def test_replacing_judge_row_removes_stale_trailing_items() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("prompt", "model", True, None, (1, 0, 1))
    evidence.observe("prompt", "model", False, None, (0,))

    assert evidence.records()[0]["irt_row"] == [0]


def test_semantic_warm_start_interpolates_two_nearest_contexts() -> None:
    evidence = PsychometricRoutingEvidence(semantic_warm_start_enabled=True)
    evidence.observe("left", "model_a", True, [1.0, 0.0])
    evidence.observe("right", "model_a", True, [0.0, 1.0])
    evidence._scores = {
        evidence.context_id("left"): {"model_a": 0.9, "model_b": 0.1},
        evidence.context_id("right"): {"model_a": 0.3, "model_b": 0.7},
    }
    evidence._fit_revision = evidence._revision

    ranked = evidence.ranked_evidence(
        iter(("model_a", "model_b")), "held-out", [1.0, 1.0]
    )

    assert [(agent_id, round(score, 6)) for agent_id, score in ranked] == [
        ("model_a", 0.6),
        ("model_b", 0.4),
    ]


def test_semantic_warm_start_defaults_to_validated_single_neighbor() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("left", "model_a", True, [1.0, 0.0])
    evidence.observe("right", "model_a", True, [0.0, 1.0])
    evidence._scores = {
        evidence.context_id("left"): {"model_a": 0.9, "model_b": 0.1},
        evidence.context_id("right"): {"model_a": 0.3, "model_b": 0.7},
    }
    evidence._fit_revision = evidence._revision

    ranked = evidence.ranked_evidence(
        ("model_a", "model_b"), "held-out", [0.9, 0.8]
    )

    assert ranked == [("model_a", 0.9), ("model_b", 0.1)]


def test_semantic_warm_start_rejects_non_positive_neighbors() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("opposite", "model_a", True, [-1.0, 0.0])
    evidence._scores = {
        evidence.context_id("opposite"): {"model_a": 0.9, "model_b": 0.1}
    }
    evidence._fit_revision = evidence._revision

    assert evidence.ranked_evidence(
        ("model_a", "model_b"), "held-out", [1.0, 0.0]
    ) == []


def test_semantic_warm_start_rejects_non_finite_embeddings() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("invalid", "model_a", True, [float("nan"), 1.0])
    evidence._scores = {
        evidence.context_id("invalid"): {"model_a": 0.9, "model_b": 0.1}
    }
    evidence._fit_revision = evidence._revision

    assert evidence.ranked_evidence(
        ("model_a", "model_b"), "held-out", [1.0, 0.0]
    ) == []


def test_cosine_is_finite_for_large_finite_embeddings() -> None:
    similarity = PsychometricRoutingEvidence._cosine(
        [1e308, 1e308], [1e308, 1e308]
    )

    assert similarity is not None
    assert math.isfinite(similarity)
    assert similarity == pytest.approx(1.0)


def test_deployment_configuration_changes_psychometric_identity() -> None:
    before = ModelAgent("model_a", "model-a", base_url="https://one.example/v1")
    after = ModelAgent("model_a", "model-b", base_url="https://two.example/v1")

    assert TaskOrchestrator._psychometric_candidate_id(
        before
    ) != TaskOrchestrator._psychometric_candidate_id(after)


def test_changed_deployment_cannot_inherit_exact_context_score() -> None:
    old_agent = ModelAgent("reused_agent", "model-old", base_url="https://old.example/v1")
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("static_first", "model-static", priority=100),
            ModelAgent(
                "reused_agent",
                "model-new",
                base_url="https://new.example/v1",
                priority=1,
            ),
        ]
    )
    old_candidate_id = TaskOrchestrator._psychometric_candidate_id(old_agent)
    context = "versioned system/user interaction"
    orchestrator._psychometric_router.observe(
        context, old_candidate_id, True, None
    )
    orchestrator._psychometric_router._scores = {
        PsychometricRoutingEvidence.context_id(context): {old_candidate_id: 1.0}
    }
    orchestrator._psychometric_router._fit_revision = (
        orchestrator._psychometric_router._revision
    )

    ranked = orchestrator._ranked_agents(
        "request", "worker", prompt_context=context
    )

    assert [agent.id for agent in ranked] == ["static_first", "reused_agent"]
