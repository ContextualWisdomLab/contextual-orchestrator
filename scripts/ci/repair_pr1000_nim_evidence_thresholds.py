"""Retire hand-selected NIM evidence-sufficiency thresholds on PR #1000.

This one-shot driver is exact-text guarded and must remove its workflow/trigger
before the canonical PR is mergeable.
"""

from __future__ import annotations

from pathlib import Path

NIM = Path("contextual_orchestrator/nim_benchmark.py")
RELEASE_TEST = Path("tests/test_nim_benchmark_release_acceptance.py")
DOC = Path("docs/nim_benchmark.md")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_runtime() -> None:
    replace_once(
        NIM,
        '''# Smoke manifests can exercise plumbing but cannot justify production routing.\nMINIMUM_PAIRED_TASK_COUNT = 30\nREQUIRED_COMPLETION_FRACTION = 0.9\n''',
        '''# Historical fixture values retained only for compatibility/tests. They are not\n# statistical sufficiency criteria and must not change evidence status or routing.\nMINIMUM_PAIRED_TASK_COUNT = 30\nREQUIRED_COMPLETION_FRACTION = 0.9\n''',
        "legacy NIM evidence-floor constants",
    )
    replace_once(
        NIM,
        '''    sufficient = (\n        locked_task_count >= MINIMUM_PAIRED_TASK_COUNT\n        and len(paired_task_ids) >= MINIMUM_PAIRED_TASK_COUNT\n        and completion_fraction >= REQUIRED_COMPLETION_FRACTION\n    )\n    return {\n        "evidence_status": (\n            "evidence_review_required" if sufficient else "insufficient_evidence"\n        ),\n        "decision_use": (\n            "production_candidate_review" if sufficient else "benchmark_smoke_only"\n        ),\n        "minimum_paired_task_count": MINIMUM_PAIRED_TASK_COUNT,\n        "required_completion_fraction": REQUIRED_COMPLETION_FRACTION,\n''',
        '''    return {\n        "evidence_status": "measurement_evidence_only",\n        "decision_use": "measurement_evidence_only",\n        "minimum_paired_task_count": None,\n        "required_completion_fraction": None,\n''',
        "NIM evidence sufficiency decision",
    )
    replace_once(
        NIM,
        '''        "minimum_paired_task_count": MINIMUM_PAIRED_TASK_COUNT,\n        "required_completion_fraction": REQUIRED_COMPLETION_FRACTION,\n        "seed": seed,\n''',
        '''        "minimum_paired_task_count": None,\n        "required_completion_fraction": None,\n        "seed": seed,\n''',
        "NIM provenance threshold authority",
    )
    replace_once(
        NIM,
        '''        f"- paired tasks: {report['evaluation']['observed_paired_task_count']} "\n        f"/ {report['evaluation']['minimum_paired_task_count']} required",\n        f"- completion fraction: {report['evaluation']['observed_completion_fraction']} "\n        f"/ {report['evaluation']['required_completion_fraction']} required",\n''',
        '''        f"- observed paired tasks: {report['evaluation']['observed_paired_task_count']}",\n        f"- observed completion fraction: {report['evaluation']['observed_completion_fraction']}",\n        "- statistical sufficiency threshold: none; a pre-registered validated evaluation design is required",\n''',
        "NIM summary threshold language",
    )


def patch_tests() -> None:
    replace_once(
        RELEASE_TEST,
        '''    assert evaluation["evidence_status"] == "evidence_review_required"\n    assert evaluation["decision_use"] == "production_candidate_review"\n    assert evaluation["minimum_paired_task_count"] == 30\n    assert evaluation["required_completion_fraction"] == 0.9\n''',
        '''    assert evaluation["evidence_status"] == "measurement_evidence_only"\n    assert evaluation["decision_use"] == "measurement_evidence_only"\n    assert evaluation["minimum_paired_task_count"] is None\n    assert evaluation["required_completion_fraction"] is None\n''',
        "release evidence-floor assertions",
    )


def patch_docs() -> None:
    replace_once(
        DOC,
        '''The bundled thirty-task manifest is an evidence-floor fixture with two exploratory\ntasks kept outside the decision set. It proves integration behavior but does not\nauthorize production routing. A report reaches\n`evidence_review_required` only when it contains at least 30 paired locked tasks\nand at least 90% successful comparison cells. Otherwise it reports\n`insufficient_evidence` and explains the shortfall.\n\nThese thresholds are explicit conservative governance floors, not universal\nstatistical guarantees. Every report keeps `routing_recommendation` null even\nwhen the floor is met; a human review remains required.\n''',
        '''The bundled thirty-task manifest is an integration fixture with two exploratory\ntasks kept outside the measurement set. It can exercise the benchmark contract\nbut cannot establish statistical sufficiency or authorize production routing.\nThe report therefore records observed paired-task and completion quantities as\nmeasurement evidence only; it does not convert them through a hand-selected\nsample-size or completion-fraction cutoff. `routing_recommendation` remains null.\nA production decision requires an independently justified, pre-registered and\nvalidated evaluation design appropriate to the estimand and deployment scope.\n''',
        "NIM evidence sufficiency documentation",
    )


def main() -> None:
    patch_runtime()
    patch_tests()
    patch_docs()


if __name__ == "__main__":
    main()
