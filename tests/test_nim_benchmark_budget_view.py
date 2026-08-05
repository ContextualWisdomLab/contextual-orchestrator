"""Buyer-facing request-plan regressions for the NVIDIA NIM benchmark."""

from contextual_orchestrator import nim_benchmark as nb


def test_planned_complete_run_requests_translates_the_internal_plan() -> None:
    """Expose complete catalog, probe, evaluation, and total request counts."""
    assert nb.planned_complete_run_requests(
        model_count=127,
        locked_task_count=10,
        max_eval_models=7,
    ) == {
        "catalog_discovery_requests": 1,
        "capability_probe_requests": 127 * len(nb.CAPABILITY_PROBE_ORDER),
        "evaluation_worker_ceiling": 7,
        "evaluation_requests": 140,
        "requests_after_catalog": 1283,
        "total_requests": 1284,
    }
