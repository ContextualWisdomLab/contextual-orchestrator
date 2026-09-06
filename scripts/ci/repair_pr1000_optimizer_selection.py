"""Retire ad-hoc optimizer ranking and evolutionary search on PR #1000.

This one-shot repair preserves descriptive measured results and Pareto dominance,
but removes hand-authored scalar/lexicographic recommendations and the unrelated
random mutation/survivor loop that was labelled "TRINITY-style" without
implementing TRINITY's trained coordinator / separable CMA-ES contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path("contextual_orchestrator/orchestrator.py")
OPT_TEST = Path("tests/test_optimizer.py")
BATCH_TEST = Path("tests/test_batch_optimizer.py")
EVOLVE_TEST = Path("tests/test_evolve_optimizer.py")
ADR = Path("docs/adr/0002-control-plane-orchestrator.md")
DOCTORING = Path("docs/doctoring/routing-literature-refresh-2026-09.md")
ARCH = Path("docs/architecture.md")
GAP = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")
BENCHMARK = Path("docs/benchmarks/2026-07-06-openai-optimizer.md")
MARKER = "## 2026-09-02 optimizer no-heuristics amendment"


def replace_def(path: Path, name: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{path}:{name}: expected one function, found {len(matches)}")
    node = matches[0]
    if node.end_lineno is None:
        raise RuntimeError(f"{path}:{name}: parser did not expose end_lineno")
    lines = text.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [replacement.rstrip() + "\n"]
    path.write_text("".join(lines), encoding="utf-8")


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: Path, marker: str, section: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + section.strip() + "\n", encoding="utf-8")


def patch_engine() -> None:
    replace_def(
        ENGINE,
        "_recommend_config",
        '''def _recommend_config(
    results: list[dict[str, Any]],
    cost_budget_usd: float | None,
) -> dict[str, Any] | None:
    """Return only a uniquely identified Pareto-dominant measured config.

    Cost/quality trade-offs are a partial order.  Without an externally
    identified utility model, lexicographic quality-first selection, a
    quality-per-cost ratio, cheapest fallback, and deterministic tie-breaking
    would each invent a utility function.  Unknown cost evidence also fails
    closed because an unmeasured candidate can not be proven dominated.
    """
    if any(row.get("cost_usd") is None for row in results):
        return None
    measured = list(results)
    if cost_budget_usd is not None:
        if not math.isfinite(cost_budget_usd) or cost_budget_usd < 0:
            raise ValueError("cost_budget_usd must be a finite nonnegative explicit constraint")
        measured = [row for row in measured if row["cost_usd"] <= cost_budget_usd]
    if not measured:
        return None
    front = _pareto_front(measured)
    if len(front) != 1:
        return None
    best = front[0]
    reason = (
        "unique Pareto-dominant measured config within explicit cost budget"
        if cost_budget_usd is not None
        else "unique Pareto-dominant measured config"
    )
    return {
        "name": best["name"],
        "quality": best["quality"],
        "cost_usd": best["cost_usd"],
        "reason": reason,
    }''',
    )
    replace_def(
        ENGINE,
        "optimize_orchestration",
        '''def optimize_orchestration(
    candidates: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    quality_fn: Any,
    cost_budget_usd: float | None = None,
    use_batch: bool = False,
    *,
    quality_evidence_kind: str | None = None,
) -> dict[str, Any]:
    """Measure candidate quality/cost without inventing a scalar utility model.

    ``quality_evidence_kind`` is mandatory whenever this evaluator is used:
    ``deterministic_ground_truth`` is reserved for directly checkable outcomes,
    while ``fast_mlsirm`` identifies the repository's psychometric/model-response
    quality boundary.  A generic unproven judge score is not admitted.

    Results remain in caller-supplied candidate order as provenance only.  The
    Pareto front is a mathematical dominance relation, not a ranking.  A
    recommendation exists only when the measured admissible set has one unique
    Pareto-dominant candidate; otherwise the decision is unresolved.
    """
    allowed_quality_evidence = {"deterministic_ground_truth", "fast_mlsirm"}
    if quality_evidence_kind not in allowed_quality_evidence:
        raise ValueError(
            "quality_evidence_kind must be deterministic_ground_truth or fast_mlsirm"
        )
    if candidates and not tasks:
        raise ValueError("tasks must be non-empty when candidates are evaluated")

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        orchestrator = candidate["orchestrator"]
        mode = candidate.get("mode", "auto")
        quality = _score_config(orchestrator, tasks, quality_fn, mode, use_batch)
        if not math.isfinite(quality) or not 0.0 <= quality <= 1.0:
            raise ValueError("quality evidence must be finite and on the declared [0, 1] scale")
        cost = orchestrator.spend_analytics()["totals"]["cost_usd"]
        if cost is not None and (not math.isfinite(cost) or cost < 0):
            raise ValueError("measured cost must be finite and nonnegative")
        results.append(
            {
                "name": candidate["name"],
                "mode": mode,
                "quality": quality,
                "cost_usd": cost,
                "task_count": len(tasks),
                "quality_evidence_kind": quality_evidence_kind,
            }
        )

    return {
        "objective": "Pareto quality-up / cost-down measurements; no implicit utility",
        "cost_budget_usd": cost_budget_usd,
        "quality_evidence_kind": quality_evidence_kind,
        "result_order": "candidate_input_order_provenance_only",
        "results": results,
        "pareto_front": [row["name"] for row in _pareto_front(results)],
        "recommended": _recommend_config(results, cost_budget_usd),
    }''',
    )
    replace_def(
        ENGINE,
        "evolve_orchestration",
        '''def evolve_orchestration(
    build_orchestrator: Any,
    search_space: dict[str, list[Any]],
    tasks: list[dict[str, Any]],
    quality_fn: Any,
    generations: int | None = None,
    population: int | None = None,
    cost_budget_usd: float | None = None,
    seed: int | None = None,
    use_batch: bool = False,
) -> dict[str, Any]:
    """Fail closed until an evaluated research-backed search implementation exists.

    The retired implementation used repository-chosen population/generation/seed
    defaults, uniform random initialization, one-gene mutation, top-half survivor
    truncation, and a lexicographic affordability/quality/cost fitness.  TRINITY
    instead optimizes a trained coordinator with separable CMA-ES; Conductor uses
    reinforcement learning; Fugu reports trained query-adaptive orchestrators.
    Calling the former loop "TRINITY-style" did not make it research-conformant.
    """
    del build_orchestrator, search_space, tasks, quality_fn
    del generations, population, cost_budget_usd, seed, use_batch
    raise RuntimeError(
        "ad-hoc evolutionary orchestration search is retired; provide a validated "
        "learned coordinator or research-backed search implementation with executable provenance"
    )''',
    )


def patch_optimizer_tests() -> None:
    OPT_TEST.write_text(
        '''"""Optimizer measurements use explicit evidence and Pareto identification only."""\n\nfrom __future__ import annotations\n\nfrom pathlib import Path\nimport sys\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n\nfrom contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402\nfrom contextual_orchestrator.orchestrator import optimize_orchestration, _pareto_front  # noqa: E402\n\n\nclass _ExactCounter:\n    def count_text(self, text: str, model: str) -> int:\n        return len(text.encode("utf-8"))\n\n\ndef _candidate(name: str, agent_id: str, price: float) -> dict:\n    orchestrator = TaskOrchestrator(\n        [ModelAgent(agent_id, "model-x", tags=("reasoning", "writing"))],\n        price_per_million={"model-x": price},\n        token_counter=_ExactCounter(),\n    )\n    return {"name": name, "orchestrator": orchestrator, "mode": "route"}\n\n\ndef _quality(task: dict, answer: str) -> float:\n    del task\n    return 0.9 if "strong_worker" in answer else 0.6\n\n\nTASKS = [{"prompt": "task one"}, {"prompt": "task two"}]\n\n\ndef _measure(candidates, *, budget=None):\n    return optimize_orchestration(\n        candidates,\n        TASKS,\n        _quality,\n        cost_budget_usd=budget,\n        quality_evidence_kind="deterministic_ground_truth",\n    )\n\n\ndef test_optimizer_measures_quality_and_cost_without_ranking_rows() -> None:\n    candidates = [\n        _candidate("cheap", "cheap_worker", 1.0),\n        _candidate("strong", "strong_worker", 50.0),\n    ]\n    report = _measure(candidates)\n    assert [row["name"] for row in report["results"]] == ["cheap", "strong"]\n    by_name = {row["name"]: row for row in report["results"]}\n    assert by_name["strong"]["quality"] == 0.9\n    assert by_name["cheap"]["quality"] == 0.6\n    assert by_name["strong"]["cost_usd"] > by_name["cheap"]["cost_usd"]\n    assert report["result_order"] == "candidate_input_order_provenance_only"\n\n\ndef test_pareto_front_keeps_nondominated_tradeoff_unresolved() -> None:\n    report = _measure([\n        _candidate("cheap", "cheap_worker", 1.0),\n        _candidate("strong", "strong_worker", 50.0),\n    ])\n    assert set(report["pareto_front"]) == {"cheap", "strong"}\n    assert report["recommended"] is None\n\n\ndef test_unique_dominance_can_be_recommended_without_scalarization() -> None:\n    rows = [\n        {"name": "a", "quality": 0.9, "cost_usd": 0.10},\n        {"name": "b", "quality": 0.8, "cost_usd": 0.20},\n        {"name": "c", "quality": 0.95, "cost_usd": 0.30},\n    ]\n    front = {row["name"] for row in _pareto_front(rows)}\n    assert front == {"a", "c"}\n\n\ndef test_explicit_budget_filters_admissible_set_without_cheapest_fallback() -> None:\n    candidates = [\n        _candidate("cheap", "cheap_worker", 1.0),\n        _candidate("strong", "strong_worker", 50.0),\n    ]\n    report = _measure(candidates, budget=0.0)\n    assert report["recommended"] is None\n\n\nif __name__ == "__main__":\n    for name, fn in sorted(globals().items()):\n        if name.startswith("test_") and callable(fn):\n            fn()\n            print(f"ok {name}")\n    print("ok")\n''',
        encoding="utf-8",
    )


def patch_batch_test() -> None:
    old_one = '''    report_batch = optimize_orchestration(\n        [{"name": "route_cfg", "orchestrator": _orch(batch_client), "mode": "route"}],\n        TASKS, lambda task, answer: 1.0 if "general_agent" in answer else 0.0, use_batch=True)\n'''
    new_one = '''    report_batch = optimize_orchestration(\n        [{"name": "route_cfg", "orchestrator": _orch(batch_client), "mode": "route"}],\n        TASKS,\n        lambda task, answer: 1.0 if "general_agent" in answer else 0.0,\n        use_batch=True,\n        quality_evidence_kind="deterministic_ground_truth",\n    )\n'''
    replace_exact(BATCH_TEST, old_one, new_one, "batch optimizer call")
    old_two = '''    report_serial = optimize_orchestration(\n        [{"name": "route_cfg", "orchestrator": _orch(serial_client), "mode": "route"}],\n        TASKS, lambda task, answer: 1.0 if "general_agent" in answer else 0.0, use_batch=False)\n'''
    new_two = '''    report_serial = optimize_orchestration(\n        [{"name": "route_cfg", "orchestrator": _orch(serial_client), "mode": "route"}],\n        TASKS,\n        lambda task, answer: 1.0 if "general_agent" in answer else 0.0,\n        use_batch=False,\n        quality_evidence_kind="deterministic_ground_truth",\n    )\n'''
    replace_exact(BATCH_TEST, old_two, new_two, "serial optimizer call")


def patch_evolve_test() -> None:
    EVOLVE_TEST.write_text(
        '''"""The former ad-hoc evolutionary optimizer is a fail-closed compatibility surface."""\n\nfrom __future__ import annotations\n\nfrom pathlib import Path\nimport sys\n\nimport pytest\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n\nfrom contextual_orchestrator.orchestrator import evolve_orchestration, _space_size  # noqa: E402\n\n\ndef test_evolutionary_search_requires_a_validated_research_implementation() -> None:\n    with pytest.raises(RuntimeError, match="validated learned coordinator or research-backed search implementation"):\n        evolve_orchestration(\n            lambda _config: None,\n            {"tier": ["small", "large"], "mode": ["route"]},\n            [{"prompt": "task"}],\n            lambda _task, _answer: 1.0,\n            generations=4,\n            population=6,\n            seed=7,\n        )\n\n\ndef test_space_size_math_remains_descriptive_only() -> None:\n    assert _space_size({"a": [1, 2, 3], "b": [1, 2]}) == 6\n    assert _space_size({}) == 1\n''',
        encoding="utf-8",
    )


def patch_docs() -> None:
    section = '''## 2026-09-02 optimizer no-heuristics amendment

The historical `optimize_orchestration` helper conflated measurement with a
utility function: it sorted by quality/cost, broke equal-quality ties by cost,
selected the cheapest model when an explicit budget admitted nothing, and
published a quality-per-dollar ratio.  Those choices are not entailed by Fugu,
TRINITY, Conductor, or the repository's measurement contracts.  The current
boundary preserves candidate-order provenance, raw measured quality/cost and
mathematical Pareto dominance.  A recommendation is identified only when the
admissible measured set has one unique Pareto-dominant candidate; otherwise it
is unresolved.  Unknown costs fail closed.

The former `evolve_orchestration` loop is also retired as decision authority.
Its fixed population/generation/seed defaults, uniform random initialization,
one-gene mutation, top-half survivor truncation and lexicographic fitness were
repository-authored choices, not TRINITY's separable CMA-ES optimization of a
trained coordinator, Conductor's reinforcement-learning procedure, or Fugu's
trained query-adaptive conductor.  It now fails closed until a validated
research-backed implementation with executable provenance is supplied.

Quality evidence is explicit: directly checkable ground-truth scoring may be
identified as `deterministic_ground_truth`; model-response quality uses
`fast_mlsirm`.  Generic unproven judge scores are not admitted by this API.

Research basis: Tang et al. (2026), *Sakana Fugu Technical Report*, arXiv
2606.21228; Xu et al. (2025), *TRINITY: An Evolved LLM Coordinator*, arXiv
2512.04695; Nielsen et al. (2025), *Learning to Orchestrate Agents in Natural
Language with the Conductor*, arXiv 2512.04388; and Sakana AI's 2026-08-10
Gemma 4 held-out validation report.
'''
    append_once(ADR, MARKER, section)
    append_once(DOCTORING, MARKER, section)
    append_once(ARCH, MARKER, section)
    append_once(GAP, MARKER, section)
    append_once(BENCHMARK, MARKER, section)
    append_once(
        CHANGELOG,
        MARKER,
        '''## 2026-09-02 optimizer no-heuristics amendment

- Retire ad-hoc optimizer ranking, cheapest fallback, quality-per-dollar decision
  score, and the unrelated random evolutionary-search loop. Preserve measured
  candidate evidence and Pareto dominance; ambiguous trade-offs fail closed and
  model-response quality requires fast-mlsirm provenance.
''',
    )


def main() -> None:
    patch_engine()
    patch_optimizer_tests()
    patch_batch_test()
    patch_evolve_test()
    patch_docs()


if __name__ == "__main__":
    main()
