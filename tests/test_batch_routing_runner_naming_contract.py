"""Naming contract for synchronous adapters over async batch clients."""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BATCH_ROUTING_MODULE = REPOSITORY_ROOT / "contextual_orchestrator" / "batch_routing.py"


def test_pg_llm_adapters_use_semantic_async_operation_runner() -> None:
    """Require both pg-llm-batch adapters to name their async bridge explicitly."""
    syntax_tree = ast.parse(BATCH_ROUTING_MODULE.read_text(encoding="utf-8"))
    runner_methods = [
        node
        for node in ast.walk(syntax_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run_async_client_operation"
    ]
    generic_runners = [
        node
        for node in ast.walk(syntax_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run"
    ]

    assert len(runner_methods) == 2
    assert not generic_runners
    assert all(method.args.args[0].arg == "async_operation" for method in runner_methods)


def test_pg_llm_adapter_callers_use_semantic_runner_name() -> None:
    """Prevent submit, poll, and retrieve paths from restoring the generic helper."""
    source_text = BATCH_ROUTING_MODULE.read_text(encoding="utf-8")

    assert source_text.count("self._run_async_client_operation(") == 6
    assert "self._run(" not in source_text
