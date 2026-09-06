"""Regressions forbidding heuristic NIM benchmark candidate decisions."""

from contextual_orchestrator import nim_benchmark as nb


def _chat_row(index: int) -> dict[str, object]:
    """Return one explicitly probed chat-eligible catalog row."""
    return {
        "model_id": f"provider/model-{index}",
        "chat_eligible": True,
    }


def test_all_chat_eligible_models_are_admitted_without_catalog_cardinality_cap() -> None:
    """A legacy max-eval value cannot evict otherwise eligible workers."""
    rows = [_chat_row(index) for index in range(9)]

    agents = nb.build_worker_agents(rows, "https://example.invalid/v1", 7)

    assert len(agents) == len(rows)
    assert {agent.model for agent in agents} == {row["model_id"] for row in rows}


def test_request_plan_reserves_every_discovered_model_without_legacy_cap() -> None:
    """Preflight reserves the exact safe upper bound before capabilities are known."""
    plan = nb.plan_complete_request_budget(
        discovered_model_count=9,
        max_eval_models=2,
        locked_task_count=1,
    )

    assert plan["planned_worker_count"] == 9
    assert plan["evaluation_reserve_request_count"] == nb.planned_evaluation_requests(9, 1)


def test_equal_hindsight_quality_remains_unresolved_without_name_tie_break() -> None:
    """Equal measured quality cannot be broken by policy or model identity."""
    summaries = [
        {
            "policy_name": "direct_single_worker:provider/a",
            "mean_task_score": 1.0,
        },
        {
            "policy_name": "direct_single_worker:provider/z",
            "mean_task_score": 1.0,
        },
    ]

    assert nb.best_single_worker_hindsight(summaries) is None
