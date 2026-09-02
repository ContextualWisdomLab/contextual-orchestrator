"""Retire heuristic NIM candidate caps and name-based quality tie-breaks on PR #1000."""

from __future__ import annotations

from pathlib import Path

NIM = Path("contextual_orchestrator/nim_benchmark.py")
RELEASE_TEST = Path("tests/test_nim_benchmark_release_acceptance.py")
CHANGELOG = Path("CHANGELOG.md")
GAP = Path("docs/product-technical-gap-baseline.md")
RESEARCH = Path("docs/doctoring/routing-literature-refresh-2026-09.md")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    """Replace exactly one reviewed source fragment or fail closed."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: Path, marker: str, addition: str) -> None:
    """Append one traceability section once."""
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


def patch_runtime() -> None:
    """Replace cardinality/name decisions with evidence-complete fail-closed rules."""
    replace_once(
        NIM,
        '''def build_worker_agents(\n    probed_models: list[dict[str, Any]],\n    base_url: str,\n    max_eval_models: int,\n) -> list[ModelAgent]:\n    """Build the evaluation worker pool from chat-eligible probed models.\n\n    Deterministic: models are already sorted by id; the pool is capped at\n    ``max_eval_models`` so a huge catalog cannot silently explode the budget.\n    """\n    if max_eval_models < 1:\n        raise BenchmarkContractError("max_eval_models must be a positive integer")\n    taken_ids: set[str] = set()\n    agents: list[ModelAgent] = []\n    for row in probed_models:\n        if not row["chat_eligible"]:\n            continue\n        if len(agents) >= max_eval_models:\n            break\n        agents.append(\n            ModelAgent(\n                id=sanitize_worker_agent_id(row["model_id"], taken_ids),\n                model=row["model_id"],\n                base_url=base_url,\n                credential_key=NIM_CREDENTIAL_NAME,\n                tags=("reasoning", "writing"),\n            )\n        )\n    return agents\n''',
        '''def build_worker_agents(\n    probed_models: list[dict[str, Any]],\n    base_url: str,\n    max_eval_models: int | None = None,\n) -> list[ModelAgent]:\n    """Build the evaluation worker pool from every observed chat-eligible model.\n\n    ``max_eval_models`` remains a validated compatibility input only. It cannot\n    remove, order, rank, or prioritize an otherwise eligible worker. Candidate\n    membership follows complete capability-probe evidence.\n    """\n    if max_eval_models is not None and (\n        isinstance(max_eval_models, bool)\n        or not isinstance(max_eval_models, int)\n        or max_eval_models < 1\n    ):\n        raise BenchmarkContractError("max_eval_models must be a positive integer")\n    taken_ids: set[str] = set()\n    agents: list[ModelAgent] = []\n    for row in probed_models:\n        if not row["chat_eligible"]:\n            continue\n        agents.append(\n            ModelAgent(\n                id=sanitize_worker_agent_id(row["model_id"], taken_ids),\n                model=row["model_id"],\n                base_url=base_url,\n                credential_key=NIM_CREDENTIAL_NAME,\n                tags=("reasoning", "writing"),\n            )\n        )\n    return agents\n''',
        "NIM worker cardinality admission",
    )
    replace_once(
        NIM,
        '''    counts = {\n        "discovered_model_count": discovered_model_count,\n        "max_eval_models": max_eval_models,\n        "locked_task_count": locked_task_count,\n    }\n    for label, value in counts.items():\n        if isinstance(value, bool) or not isinstance(value, int) or value < 1:\n            raise BenchmarkContractError(f"{label} must be a positive integer")\n    planned_worker_count = min(discovered_model_count, max_eval_models)\n''',
        '''    counts = {\n        "discovered_model_count": discovered_model_count,\n        "locked_task_count": locked_task_count,\n    }\n    for label, value in counts.items():\n        if isinstance(value, bool) or not isinstance(value, int) or value < 1:\n            raise BenchmarkContractError(f"{label} must be a positive integer")\n    if max_eval_models is not None and (\n        isinstance(max_eval_models, bool)\n        or not isinstance(max_eval_models, int)\n        or max_eval_models < 1\n    ):\n        raise BenchmarkContractError("max_eval_models must be a positive integer")\n    # Before capability probes, every discovered model can in principle be chat\n    # eligible. Reserving all discovered models is the exact safe upper bound;\n    # a hand-selected catalog cardinality cannot decide evaluation admission.\n    planned_worker_count = discovered_model_count\n''',
        "NIM request-plan candidate cap",
    )
    replace_once(
        NIM,
        '''def best_single_worker_hindsight(\n    summaries: list[dict[str, Any]],\n) -> dict[str, Any] | None:\n    """The best direct single worker selected in hindsight on the locked split."""\n    direct = [\n        row\n        for row in summaries\n        if row["policy_name"].startswith("direct_single_worker:")\n    ]\n    if not direct:\n        return None\n    best = max(direct, key=lambda row: (row["mean_task_score"], row["policy_name"]))\n    return {\n        "policy_name": best["policy_name"],\n        "model_id": best["policy_name"].split(":", 1)[1],\n        "mean_task_score": best["mean_task_score"],\n        "selection_basis": "hindsight_argmax_mean_locked_score",\n    }\n''',
        '''def best_single_worker_hindsight(\n    summaries: list[dict[str, Any]],\n) -> dict[str, Any] | None:\n    """Return a uniquely identified direct worker at the maximum measured score.\n\n    Equal observed quality is unresolved: provider/model/policy identity cannot\n    act as an undocumented tie-break.\n    """\n    direct = [\n        row\n        for row in summaries\n        if row["policy_name"].startswith("direct_single_worker:")\n    ]\n    if not direct:\n        return None\n    best_score = max(row["mean_task_score"] for row in direct)\n    winners = [row for row in direct if row["mean_task_score"] == best_score]\n    if len(winners) != 1:\n        return None\n    best = winners[0]\n    return {\n        "policy_name": best["policy_name"],\n        "model_id": best["policy_name"].split(":", 1)[1],\n        "mean_task_score": best["mean_task_score"],\n        "selection_basis": "unique_argmax_mean_locked_score",\n    }\n''',
        "NIM name-based hindsight tie-break",
    )
    replace_once(
        NIM,
        '''    max_output_tokens: int | None = None,\n    max_eval_models: int = 7,\n    seed: int = 7,\n''',
        '''    max_output_tokens: int | None = None,\n    max_eval_models: int | None = None,\n    seed: int = 7,\n''',
        "NIM run cardinality default after token-allocation repair",
    )
    replace_once(
        NIM,
        '''        max_eval_models: Maximum chat-eligible workers in policy evaluation.\n''',
        '''        max_eval_models: Deprecated compatibility input; when supplied it is\n            validated but cannot cap or rank chat-eligible workers.\n''',
        "NIM run cardinality documentation",
    )
    replace_once(
        NIM,
        '''        "max_eval_models": max_eval_models,\n        "max_workflow_depth": MAX_WORKFLOW_DEPTH,\n''',
        '''        "max_eval_models": None,\n        "evaluation_candidate_policy": "all_observed_chat_eligible_models",\n        "max_workflow_depth": MAX_WORKFLOW_DEPTH,\n''',
        "NIM provenance cardinality authority",
    )
    replace_once(
        NIM,
        '''    parser.add_argument("--max-eval-models", type=int, default=7)\n''',
        '''    parser.add_argument(\n        "--max-eval-models",\n        type=int,\n        default=None,\n        help="Deprecated compatibility input; does not cap evaluation candidates.",\n    )\n''',
        "NIM CLI cardinality default",
    )


def patch_release_tests() -> None:
    """Align release evidence with the exact all-candidate request bound."""
    replace_once(
        RELEASE_TEST,
        '''        "evaluation_reserve_request_count": 260,\n        "planned_worker_count": 7,\n        "total_required_request_count": 1404,\n''',
        '''        "evaluation_reserve_request_count": 2660,\n        "planned_worker_count": 127,\n        "total_required_request_count": 3804,\n''',
        "127-model internal request plan",
    )
    replace_once(
        RELEASE_TEST,
        '''        "evaluation_worker_ceiling": 7,\n        "evaluation_requests": 780,\n        "requests_after_catalog": 127 * 9 + 780,\n        "total_requests": 1924,\n''',
        '''        "evaluation_worker_ceiling": 127,\n        "evaluation_requests": 7980,\n        "requests_after_catalog": 127 * 9 + 7980,\n        "total_requests": 9124,\n''',
        "127-model buyer request plan",
    )
    replace_once(
        RELEASE_TEST,
        '''        match="complete benchmark needs 1924 requests but configured cap is 1923",\n''',
        '''        match="complete benchmark needs 9124 requests but configured cap is 9123",\n''',
        "one-short request-plan error",
    )
    replace_once(
        RELEASE_TEST,
        '''            max_total_requests=1923,\n            max_eval_models=7,\n''',
        '''            max_total_requests=9123,\n            max_eval_models=7,\n''',
        "one-short request-plan allowance",
    )


def patch_traceability() -> None:
    """Record causal owner and evidence basis without inventing a replacement score."""
    replace_once(
        CHANGELOG,
        '''- Remove the NIM benchmark character-count token heuristic and weighted cheapest-worker selector. Benchmark token/cost evidence now requires complete provider-reported usage, and ambiguous or incomplete price vectors fail closed.\n''',
        '''- Remove the NIM benchmark character-count token heuristic and weighted cheapest-worker selector. Benchmark token/cost evidence now requires complete provider-reported usage, and ambiguous or incomplete price vectors fail closed.\n- Remove the NIM evaluation cardinality cap and model-name quality tie-break. Every capability-proven chat-eligible model remains in the benchmark, preflight reserves the exact all-discovered upper bound, and equal measured single-worker quality remains unresolved.\n''',
        "NIM candidate changelog",
    )
    append_once(
        RESEARCH,
        "## NIM candidate-admission boundary (2026-09-02)",
        '''## NIM candidate-admission boundary (2026-09-02)\n\nThe former seven-worker evaluation ceiling and model/policy-name tie-break were\nrepository-authored controls, not results of Fugu, Conductor, TRINITY, a\nprovider standard, or a validated statistical model. The benchmark therefore\nadmits every model with observed chat-eligibility evidence. Before capability\nprobes, every discovered model is a possible eligible worker, so reserving the\nfull discovered count is the exact safe request upper bound rather than a\nranking policy. Equal measured single-worker quality remains unidentified and\nreturns no hindsight winner. This implements the research register's narrower\nconclusion that learned routing evidence does not authorize hand-set catalog\ncaps or identity-based tie-breaks.\n''',
    )
    append_once(
        GAP,
        "### 2026-09-02 NIM evaluation-candidate admission repair",
        '''### 2026-09-02 NIM evaluation-candidate admission repair\n\nRoot cause: `build_worker_agents` admitted only the first seven chat-eligible\nmodels in model-id order, request planning reserved that same arbitrary subset,\nand `best_single_worker_hindsight` broke equal measured quality by policy/model\nname. Causal owner: the optional NIM benchmark harness. Repair: retain every\ncapability-proven chat-eligible worker, reserve all discovered models as the\nmathematically exact pre-probe upper bound, and leave equal-quality hindsight\nselection unresolved. Regression evidence is `tests/test_nim_benchmark_no_heuristic_candidates.py`; hosted exact-head checks after the one-shot repair remain authoritative.\n''',
    )


def main() -> None:
    """Apply the exact-text candidate-admission repair."""
    patch_runtime()
    patch_release_tests()
    patch_traceability()


if __name__ == "__main__":
    main()
