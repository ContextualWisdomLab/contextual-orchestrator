"""Fast-MLSIRM contextual ability ordering for cold start and failover."""

from __future__ import annotations

import numpy as np
from pathlib import Path

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.psychometric_routing import PsychometricRoutingEvidence


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
        lambda agent_ids, prompt, vector: [("quality_first", 0.91)],
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
        lambda agent_ids, prompt, vector: [("quality_backup", 0.88)],
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

    assert records == [
        {
            "context_id": PsychometricRoutingEvidence.context_id(
                "system secret/user request"
            ),
            "agent_id": "model_a",
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
