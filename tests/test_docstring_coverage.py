"""Public production API docstring coverage contract."""

from __future__ import annotations

import ast
from pathlib import Path


def test_public_production_api_has_complete_docstrings() -> None:
    """Require docstrings on public modules, classes, functions, and methods."""
    source_root = Path(__file__).resolve().parents[1] / "contextual_orchestrator"
    missing: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if ast.get_docstring(tree) is None:
            missing.append(f"{path.relative_to(source_root)}:module")
        for node in tree.body:
            candidates = [node]
            if isinstance(node, ast.ClassDef):
                candidates.extend(node.body)
            for candidate in candidates:
                if (
                    isinstance(candidate, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and not candidate.name.startswith("_")
                    and ast.get_docstring(candidate) is None
                ):
                    missing.append(
                        f"{path.relative_to(source_root)}:{candidate.lineno}:{candidate.name}"
                    )
    assert missing == []
