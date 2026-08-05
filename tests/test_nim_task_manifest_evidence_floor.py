"""Release acceptance for the locked NIM evaluation manifest and request ceiling."""

from __future__ import annotations

import inspect
from pathlib import Path

from contextual_orchestrator import nim_benchmark as nb


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TASK_MANIFEST_PATH = REPOSITORY_ROOT / "examples" / "nim_task_manifest.json"
BENCHMARK_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "nim-benchmark.yml"
BENCHMARK_GUIDE_PATH = REPOSITORY_ROOT / "docs" / "nim_benchmark.md"
BENCHMARK_SOURCE_PATH = REPOSITORY_ROOT / "contextual_orchestrator" / "nim_benchmark.py"


def test_locked_manifest_reaches_the_declared_paired_evidence_floor() -> None:
    """Keep the scheduled benchmark capable of producing non-smoke paired evidence."""
    manifest = nb.load_task_manifest(str(TASK_MANIFEST_PATH))
    locked_tasks = nb.locked_evaluation_tasks(manifest)

    assert len(locked_tasks) == nb.MINIMUM_PAIRED_TASK_COUNT == 30
    assert len({task["task_id"] for task in locked_tasks}) == 30


def test_scheduled_ceiling_reserves_a_complete_127_model_run() -> None:
    """Cover every probe and thirty-task policy cell within one bounded live run."""
    manifest = nb.load_task_manifest(str(TASK_MANIFEST_PATH))
    locked_task_count = len(nb.locked_evaluation_tasks(manifest))
    plan = nb.plan_complete_request_budget(
        discovered_model_count=127,
        locked_task_count=locked_task_count,
        max_eval_models=7,
    )
    workflow = BENCHMARK_WORKFLOW_PATH.read_text(encoding="utf-8")
    guide = BENCHMARK_GUIDE_PATH.read_text(encoding="utf-8")

    assert plan == {
        "catalog_request_count": 1,
        "capability_probe_request_count": 1143,
        "evaluation_reserve_request_count": 420,
        "planned_worker_count": 7,
        "total_required_request_count": 1564,
    }
    assert 'echo "max_requests=2000"' in workflow
    assert "--max-total-requests 2000" in guide


def test_default_request_caps_can_run_the_bundled_thirty_task_manifest() -> None:
    """Keep API, CLI, and manual workflow defaults above the dry-run plan."""
    workflow = BENCHMARK_WORKFLOW_PATH.read_text(encoding="utf-8")
    source = BENCHMARK_SOURCE_PATH.read_text(encoding="utf-8")
    default_request_cap = inspect.signature(nb.run_benchmark).parameters[
        "max_total_requests"
    ].default
    dry_plan = nb.plan_complete_request_budget(
        discovered_model_count=len(nb._DRY_RUN_MODEL_BEHAVIOR),
        locked_task_count=nb.MINIMUM_PAIRED_TASK_COUNT,
        max_eval_models=7,
    )

    assert dry_plan["total_required_request_count"] == 529
    assert default_request_cap == 2000
    assert 'parser.add_argument("--max-total-requests", type=int, default=2000)' in source
    assert 'default: 2000' in workflow
