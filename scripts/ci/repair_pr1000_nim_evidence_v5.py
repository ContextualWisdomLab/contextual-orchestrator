"""Reconcile exact-head NIM repair regressions and emit bounded dry-run RCA evidence."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.ci import repair_pr1000_nim_evidence_v4 as v4

TESTS = Path("tests/test_nim_benchmark.py")


def _replace_once(path: Path, old: str, new: str, label: str) -> None:
    """Replace one exact generated fragment or fail closed on drift."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_frozen_agent_test() -> None:
    """Construct endpoint-adjusted frozen ModelAgent fixtures non-destructively."""
    tests = TESTS.read_text(encoding="utf-8")
    if "import dataclasses\n" not in tests:
        if tests.count("import contextlib\n") != 1:
            raise RuntimeError("test imports: expected one contextlib import")
        tests = tests.replace("import contextlib\n", "import contextlib\nimport dataclasses\n", 1)
        TESTS.write_text(tests, encoding="utf-8")
    _replace_once(
        TESTS,
        """    agents = _mock_agents("dryrun/chat-basic", "dryrun/chat-vision")
    for agent in agents:
        agent.base_url = nb.NIM_DEFAULT_ENDPOINT
""",
        """    agents = [
        dataclasses.replace(agent, base_url=nb.NIM_DEFAULT_ENDPOINT)
        for agent in _mock_agents("dryrun/chat-basic", "dryrun/chat-vision")
    ]
""",
        "frozen ModelAgent endpoint fixture",
    )


def emit_dry_run_diagnostic() -> None:
    """Print bounded policy outcomes from the repaired in-process benchmark."""
    from contextual_orchestrator import nim_benchmark as nb

    with tempfile.TemporaryDirectory() as output_dir:
        report = nb.run_benchmark(
            "dry_run",
            "examples/nim_task_manifest.json",
            "examples/nim_pricing_scenario.json",
            output_dir,
            max_total_requests=900,
        )
    cells = report["evaluation"]["evaluation_cells"]
    diagnostic = [
        {
            "policy_name": cell["policy_name"],
            "run_outcome": cell["run_outcome"],
            "outcome_reason": cell["outcome_reason"],
            "token_usage_source": cell["token_usage_source"],
        }
        for cell in cells[:20]
    ]
    print("PR1000_DRY_RUN_DIAGNOSTIC=" + json.dumps(diagnostic, sort_keys=True))


def main() -> None:
    """Run v4, repair the frozen fixture, then expose dry-run failure evidence."""
    v4.main()
    patch_frozen_agent_test()
    emit_dry_run_diagnostic()


if __name__ == "__main__":
    main()
