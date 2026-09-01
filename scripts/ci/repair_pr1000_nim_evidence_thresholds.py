"""Retire hand-selected NIM decision thresholds on PR #1000.

This one-shot driver is exact-text guarded and must remove its workflow/trigger
before the canonical PR is mergeable. Historical dry-run fixture quantities may
remain for deterministic non-authoritative tests, but they cannot be production
routing, evidence-sufficiency, or test-time-compute defaults.
"""

from __future__ import annotations

from pathlib import Path

NIM = Path("contextual_orchestrator/nim_benchmark.py")
RELEASE_TEST = Path("tests/test_nim_benchmark_release_acceptance.py")
DOC = Path("docs/nim_benchmark.md")
GAP = Path("docs/product-technical-gap-baseline.md")
RESEARCH = Path("docs/doctoring/routing-literature-refresh-2026-09.md")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: Path, marker: str, addition: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


def patch_runtime() -> None:
    replace_once(
        NIM,
        '''# Provider output remains capped at 264 tokens by default. The equal cell-wide\n# prompt-plus-completion budget scales with the maximum five-call envelope so a\n# fixed conduct workflow can carry its prompts without being starved. The\n# eight-token margin over the historical 256 keeps the locked 30-task\n# manifest's tightest conduct_bounded task (four-call accumulated prompt\n# context) inside its equal budget under the current deterministic dry-run\n# token estimate; see test_smoke_manifest_cannot_authorize_production_routing.\nDEFAULT_MAX_OUTPUT_TOKENS = 264\nDEFAULT_POLICY_TOTAL_TOKEN_BUDGET = MAX_WORKFLOW_DEPTH * DEFAULT_MAX_OUTPUT_TOKENS\n''',
        '''# Historical deterministic dry-run fixture only. The former 256 + 8 margin was\n# hand-selected and therefore cannot allocate live test-time compute. Live runs\n# require an explicit output-token cap from the caller's governed evaluation\n# design. Compatibility constants remain non-authoritative for fixtures/tests.\nDRY_RUN_FIXTURE_MAX_OUTPUT_TOKENS = 264\nDEFAULT_MAX_OUTPUT_TOKENS = DRY_RUN_FIXTURE_MAX_OUTPUT_TOKENS\nDEFAULT_POLICY_TOTAL_TOKEN_BUDGET = (\n    MAX_WORKFLOW_DEPTH * DRY_RUN_FIXTURE_MAX_OUTPUT_TOKENS\n)\n''',
        "NIM hand-selected output-token default",
    )
    replace_once(
        NIM,
        '''    total_token_budget: int = DEFAULT_POLICY_TOTAL_TOKEN_BUDGET,\n    maximum_calls: int = MAX_WORKFLOW_DEPTH,\n''',
        '''    total_token_budget: int | None = None,\n    maximum_calls: int = MAX_WORKFLOW_DEPTH,\n''',
        "policy total-token default",
    )
    replace_once(
        NIM,
        '''    tasks = locked_evaluation_tasks(manifest)\n    if not tasks:\n        raise BenchmarkContractError("task manifest has no locked evaluation tasks")\n    planned = planned_evaluation_requests(len(agents), len(tasks))\n''',
        '''    tasks = locked_evaluation_tasks(manifest)\n    if not tasks:\n        raise BenchmarkContractError("task manifest has no locked evaluation tasks")\n    if total_token_budget is None:\n        raise BenchmarkContractError(\n            "total_token_budget requires an explicit governed evaluation allocation"\n        )\n    planned = planned_evaluation_requests(len(agents), len(tasks))\n''',
        "policy explicit total-token allocation",
    )
    replace_once(
        NIM,
        '''    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,\n    max_eval_models: int = 7,\n''',
        '''    max_output_tokens: int | None = None,\n    max_eval_models: int = 7,\n''',
        "benchmark output-token default",
    )
    replace_once(
        NIM,
        '''    if (\n        isinstance(max_output_tokens, bool)\n        or not isinstance(max_output_tokens, int)\n        or max_output_tokens < 1\n    ):\n        raise BenchmarkContractError("max_output_tokens must be a positive integer")\n''',
        '''    if max_output_tokens is None:\n        if run_mode == "dry_run":\n            max_output_tokens = DRY_RUN_FIXTURE_MAX_OUTPUT_TOKENS\n        else:\n            raise BenchmarkContractError(\n                "live benchmark requires an explicit governed max_output_tokens allocation"\n            )\n    if (\n        isinstance(max_output_tokens, bool)\n        or not isinstance(max_output_tokens, int)\n        or max_output_tokens < 1\n    ):\n        raise BenchmarkContractError("max_output_tokens must be a positive integer")\n''',
        "live output-token fail-closed validation",
    )
    replace_once(
        NIM,
        '''    parser.add_argument(\n        "--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS\n    )\n''',
        '''    parser.add_argument(\n        "--max-output-tokens",\n        type=int,\n        default=None,\n        help=(\n            "Explicit governed per-provider-call output-token cap; required for live runs"\n        ),\n    )\n''',
        "CLI output-token default",
    )
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
        '''  --max-total-requests 2000 \\\n  --max-output-tokens 264 \\\n  --git-sha "$GITHUB_SHA" \\\n''',
        '''  --max-total-requests 2000 \\\n  --max-output-tokens "$NIM_BENCHMARK_MAX_OUTPUT_TOKENS" \\\n  --git-sha "$GITHUB_SHA" \\\n''',
        "live CLI output-token example",
    )
    replace_once(
        DOC,
        '''`--max-output-tokens` is the per-provider-call output cap. The equal\ncell-wide prompt-plus-completion budget is five times that cap by default\n(`1,320` tokens), which leaves the fixed five-call conduct workflow enough room\nfor its prompts while keeping the same cell budget for every policy.\n''',
        '''`--max-output-tokens` is the explicit per-provider-call output cap for a live\nbenchmark. There is no repository-authored live default: the caller must supply\na value justified by the governed evaluation design or the run fails closed.\nThe equal cell-wide prompt-plus-completion allowance is then derived exactly as\nthat explicit cap multiplied by the declared workflow-step envelope. The value\n`264` remains only as a deterministic dry-run fixture and is not production\nallocation evidence.\n''',
        "output-token documentation",
    )
    replace_once(
        DOC,
        '''The bundled thirty-task manifest is an evidence-floor fixture with two exploratory\ntasks kept outside the decision set. It proves integration behavior but does not\nauthorize production routing. A report reaches\n`evidence_review_required` only when it contains at least 30 paired locked tasks\nand at least 90% successful comparison cells. Otherwise it reports\n`insufficient_evidence` and explains the shortfall.\n\nThese thresholds are explicit conservative governance floors, not universal\nstatistical guarantees. Every report keeps `routing_recommendation` null even\nwhen the floor is met; a human review remains required.\n''',
        '''The bundled thirty-task manifest is an integration fixture with two exploratory\ntasks kept outside the measurement set. It can exercise the benchmark contract\nbut cannot establish statistical sufficiency or authorize production routing.\nThe report therefore records observed paired-task and completion quantities as\nmeasurement evidence only; it does not convert them through a hand-selected\nsample-size or completion-fraction cutoff. `routing_recommendation` remains null.\nA production decision requires an independently justified, pre-registered and\nvalidated evaluation design appropriate to the estimand and deployment scope.\n''',
        "NIM evidence sufficiency documentation",
    )
    append_once(
        RESEARCH,
        "## NIM output-allocation boundary (2026-09-02)",
        '''## NIM output-allocation boundary (2026-09-02)\n\nThe prior live default of 264 output tokens was derived from a deterministic\ndry-run observation (256 plus an eight-token margin), not from Fugu, Conductor,\nTRINITY, a provider contract, or a validated allocation model. It is therefore\nretained only as a non-authoritative dry-run fixture. Live NIM benchmarking now\nrequires an explicit governed output allocation and fails closed when it is\nabsent. This preserves the research register's narrower conclusion: learned\nrouting papers justify empirically evaluated decision policies, not hand-set\ncompute budgets.\n''',
    )
    append_once(
        GAP,
        "### 2026-09-02 NIM output-token allocation repair",
        '''### 2026-09-02 NIM output-token allocation repair\n\nRoot cause: the optional NIM benchmark used a hand-selected 264-token live\ndefault (historical 256 plus an eight-token dry-run margin), and\n`evaluate_policies` exposed the derived token allowance as an implicit default.\nRepair: live runs and direct policy evaluation require explicit governed token\nallocations; the 264 value remains deterministic dry-run fixture data only.\nExact-head verification is supplied by PR #1000's source-fix workflow and fresh\nrequired checks; predecessor results are non-authoritative after this change.\n''',
    )


def main() -> None:
    patch_runtime()
    patch_tests()
    patch_docs()


if __name__ == "__main__":
    main()
