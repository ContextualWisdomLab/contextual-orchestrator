"""Complete PR #1000 optimizer repair with executable-provenance fail-closed semantics.

The earlier optimizer one-shot correctly removes lexicographic/ratio/cheapest
selection and the ad-hoc evolutionary loop, but its proposed
``quality_evidence_kind='fast_mlsirm'`` string can label an arbitrary callable
as psychometric evidence.  A string is not executable provenance.  This
follow-up first applies that repair when it is still present, then retires the
remaining unvalidated scalar quality aggregation/optimizer entry point.  Exact
context model-response routing continues to use ``PsychometricRoutingEvidence``,
which imports and fits fast-mlsirm directly.
"""

from __future__ import annotations

import ast
from pathlib import Path
import runpy

ENGINE = Path("contextual_orchestrator/orchestrator.py")
OPT_TEST = Path("tests/test_optimizer.py")
BATCH_TEST = Path("tests/test_batch_optimizer.py")
DISPATCH_TEST = Path("tests/test_orchestrator_dispatch_boundaries.py")
OLD_REPAIR = Path("scripts/ci/repair_pr1000_optimizer_selection.py")
ADR = Path("docs/adr/0002-control-plane-orchestrator.md")
DOCTORING = Path("docs/doctoring/routing-literature-refresh-2026-09.md")
ARCH = Path("docs/architecture.md")
GAP = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")
BENCHMARK = Path("docs/benchmarks/2026-07-06-openai-optimizer.md")
MARKER = "## 2026-09-02 optimizer executable-provenance amendment"


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


def append_once(path: Path, marker: str, section: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + section.strip() + "\n", encoding="utf-8")


def apply_predecessor_repair_if_present() -> None:
    if OLD_REPAIR.exists():
        runpy.run_path(str(OLD_REPAIR), run_name="__main__")
    source = ENGINE.read_text(encoding="utf-8")
    required = (
        "unique Pareto-dominant measured config",
        "ad-hoc evolutionary orchestration search is retired",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise RuntimeError(
            "predecessor optimizer repair invariants missing: " + ", ".join(missing)
        )


def patch_engine() -> None:
    replace_def(
        ENGINE,
        "_score_config",
        '''def _score_config(
    orchestrator: TaskOrchestrator,
    tasks: list[dict[str, Any]],
    quality_fn: Any,
    mode: str,
    use_batch: bool,
) -> float:
    """Fail closed: unvalidated scalar response-quality aggregation is retired.

    The former helper averaged caller-provided task scores with equal implicit
    weight.  The repository has no executable sampling/aggregation/calibration
    contract establishing that mean as the deployment estimand.  Reference-free
    model-response evidence belongs in the fast-mlsirm-backed psychometric path;
    deterministic experiments need their own validated design adapter.
    """
    del orchestrator, tasks, quality_fn, mode, use_batch
    raise RuntimeError(
        "unvalidated scalar quality aggregation is retired; use a validated evaluation "
        "adapter with executable sampling, aggregation, calibration, and uncertainty provenance"
    )''',
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
    """Fail closed until optimizer evaluation has executable provenance.

    A string such as ``fast_mlsirm`` cannot prove that an arbitrary callable
    actually invoked fast-mlsirm, nor can ``deterministic_ground_truth`` prove a
    sampling or aggregation design.  Exact-context reference-free/model-response
    routing uses :class:`PsychometricRoutingEvidence`, whose fit imports
    fast-mlsirm directly.  This cross-task optimizer remains unavailable until a
    validated adapter exposes the estimand, sampling design, aggregation,
    calibration, uncertainty, and executable provenance instead of a label.
    """
    del candidates, tasks, quality_fn, cost_budget_usd, use_batch
    if quality_evidence_kind == "fast_mlsirm":
        raise RuntimeError(
            "model-response quality must use the fast-mlsirm-backed psychometric evidence "
            "path; a string label is not executable provenance"
        )
    raise RuntimeError(
        "optimizer selection requires a validated evaluation adapter with executable "
        "sampling, aggregation, calibration, and uncertainty provenance"
    )''',
    )


def patch_optimizer_test() -> None:
    OPT_TEST.write_text(
        '''"""Optimizer compatibility surfaces are descriptive or fail closed."""\n\nfrom __future__ import annotations\n\nimport pytest\n\nfrom contextual_orchestrator.orchestrator import _pareto_front, optimize_orchestration\n\n\ndef test_pareto_front_is_descriptive_partial_order_only() -> None:\n    rows = [\n        {"name": "a", "quality": 0.9, "cost_usd": 0.10},\n        {"name": "b", "quality": 0.8, "cost_usd": 0.20},\n        {"name": "c", "quality": 0.95, "cost_usd": 0.30},\n    ]\n    assert {row["name"] for row in _pareto_front(rows)} == {"a", "c"}\n\n\ndef test_optimizer_requires_validated_evaluation_adapter() -> None:\n    with pytest.raises(RuntimeError, match="validated evaluation adapter"):\n        optimize_orchestration([], [], lambda _task, _answer: 1.0)\n\n\ndef test_fast_mlsirm_label_is_not_executable_provenance() -> None:\n    with pytest.raises(RuntimeError, match="fast-mlsirm-backed"):\n        optimize_orchestration(\n            [], [], lambda _task, _answer: 1.0, quality_evidence_kind="fast_mlsirm"\n        )\n''',
        encoding="utf-8",
    )


def patch_batch_optimizer_tests() -> None:
    replace_def(
        BATCH_TEST,
        "test_optimizer_use_batch_routes_via_batch_and_matches_serial",
        '''def test_optimizer_use_batch_routes_via_batch_and_matches_serial() -> None:
    batch_client = _CountingClient()
    with pytest.raises(RuntimeError, match="validated evaluation adapter"):
        optimize_orchestration(
            [{"name": "route_cfg", "orchestrator": _orch(batch_client), "mode": "route"}],
            TASKS,
            lambda _task, _answer: 1.0,
            use_batch=True,
            quality_evidence_kind="deterministic_ground_truth",
        )
    assert batch_client.batch_calls == 0 and batch_client.chat_calls == 0''',
    )
    replace_def(
        BATCH_TEST,
        "test_conduct_config_stays_serial_even_with_use_batch",
        '''def test_conduct_config_stays_serial_even_with_use_batch() -> None:
    client = _CountingClient()
    with pytest.raises(RuntimeError, match="validated evaluation adapter"):
        optimize_orchestration(
            [{"name": "conduct_cfg", "orchestrator": _orch(client), "mode": "conduct"}],
            TASKS[:1],
            lambda _task, _answer: 1.0,
            use_batch=True,
            quality_evidence_kind="deterministic_ground_truth",
        )
    assert client.batch_calls == 0 and client.chat_calls == 0''',
    )


def patch_dispatch_test() -> None:
    replace_def(
        DISPATCH_TEST,
        "test_recommend_config_prefers_budget_fit_then_cheapest_fallback",
        '''def test_recommend_config_requires_unique_pareto_dominance() -> None:
    assert _recommend_config([], cost_budget_usd=1.0) is None
    tradeoff = [
        {"name": "cheap", "quality": 5, "cost_usd": 0.5},
        {"name": "best", "quality": 9, "cost_usd": 2.0},
        {"name": "mid", "quality": 8, "cost_usd": 1.5},
    ]
    assert _recommend_config(tradeoff, cost_budget_usd=1.6) is None
    assert _recommend_config(tradeoff, cost_budget_usd=0.25) is None
    assert _recommend_config(tradeoff, cost_budget_usd=None) is None
    dominant = [
        {"name": "dominant", "quality": 9, "cost_usd": 0.5},
        {"name": "dominated", "quality": 8, "cost_usd": 1.5},
    ]
    assert _recommend_config(dominant, cost_budget_usd=None)["name"] == "dominant"''',
    )


def patch_docs() -> None:
    section = '''## 2026-09-02 optimizer executable-provenance amendment

A follow-up RCA found that the first no-heuristics optimizer repair still
accepted `quality_evidence_kind="fast_mlsirm"` beside an arbitrary Python
callable. That was only a provenance label: it did not execute fast-mlsirm and
therefore could let an answerless/reference-free judge bypass the required
psychometric boundary. The same generic helper also averaged task scores without
an executable sampling/aggregation design establishing that arithmetic mean as
the deployment estimand.

The generic cross-task optimizer and its scalar aggregation helper now fail
closed. Exact-context model-response routing continues through
`PsychometricRoutingEvidence`, which directly imports fast-mlsirm, fits the
observed dichotomous response matrix, requires convergence, and leaves unseen
contexts and tied fitted probabilities unresolved. A future optimizer may reopen
only with an executable validated adapter that identifies its estimand, sampling
design, aggregation, calibration and uncertainty; a string label is not enough.
The mathematically defined Pareto relation remains available as descriptive
partial-order evidence, not as a substitute utility function.

Research basis remains the learned/evaluated coordinator boundary documented in
Tang et al. (2026), *Sakana Fugu Technical Report* (arXiv:2606.21228); Xu et al.
(2025), *TRINITY: An Evolved LLM Coordinator* (arXiv:2512.04695); and Nielsen
et al. (2025), *Learning to Orchestrate Agents in Natural Language with the
Conductor* (arXiv:2512.04388). The psychometric execution boundary is the
repository's fast-mlsirm MLSRM/IRT contract rather than an application-authored
score aggregation.
'''
    for path in (ADR, DOCTORING, ARCH, GAP, BENCHMARK):
        append_once(path, MARKER, section)
    append_once(
        CHANGELOG,
        MARKER,
        '''## 2026-09-02 optimizer executable-provenance amendment

- Fail closed on generic cross-task optimizer quality evaluation: a
  `fast_mlsirm` string label cannot substitute for an actual fast-mlsirm fit,
  and unvalidated equal-weight task-score aggregation is no longer decision
  authority. Exact-context psychometric routing retains direct fast-mlsirm
  execution and ambiguous evidence remains unresolved.
''',
    )


def main() -> None:
    apply_predecessor_repair_if_present()
    patch_engine()
    patch_optimizer_test()
    patch_batch_optimizer_tests()
    patch_dispatch_test()
    patch_docs()


if __name__ == "__main__":
    main()
