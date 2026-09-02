"""Naming contracts for Contextual Orchestrator cost-ledger internals."""

from __future__ import annotations

import ast
from pathlib import Path


COST_LEDGER_SOURCE = Path(__file__).parents[1] / "contextual_orchestrator" / "cost_ledger.py"


def test_non_blocking_ledger_worker_uses_semantic_method_name() -> None:
    """Keep the background usage-ledger worker distinct from generic run helpers."""

    source_tree = ast.parse(COST_LEDGER_SOURCE.read_text(encoding="utf-8"))
    ledger_store_class = next(
        node
        for node in source_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "NonBlockingLedgerStore"
    )
    worker_method_names = {
        node.name
        for node in ledger_store_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_run_usage_worker" in worker_method_names
    assert "_run" not in worker_method_names
