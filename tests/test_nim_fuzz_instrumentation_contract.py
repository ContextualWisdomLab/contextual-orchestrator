"""Contracts for coverage-guided instrumentation of the NIM catalog parser."""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPOSITORY_ROOT / "fuzz" / "fuzz_nim_catalog.py"


def _instrumented_imports() -> set[str]:
    """Return module names imported inside ``atheris.instrument_imports``."""
    module = ast.parse(HARNESS_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.With):
            continue
        if not any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and isinstance(item.context_expr.func.value, ast.Name)
            and item.context_expr.func.value.id == "atheris"
            and item.context_expr.func.attr == "instrument_imports"
            for item in node.items
        ):
            continue
        for statement in node.body:
            if isinstance(statement, ast.Import):
                imported.update(alias.name for alias in statement.names)
            elif isinstance(statement, ast.ImportFrom) and statement.module:
                imported.add(statement.module)
    return imported


def test_nim_parser_module_is_imported_inside_atheris_instrumentation() -> None:
    """Parser branches must be loaded while Atheris import hooks are active."""
    imported = _instrumented_imports()

    assert "contextual_orchestrator.nim_benchmark" in imported
    assert "fuzz.targets" in imported
