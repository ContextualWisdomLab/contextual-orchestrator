"""Regressions for the package's production-versus-test dependency boundary."""

from __future__ import annotations

import ast
from pathlib import Path
import re


PROJECT_METADATA = Path("pyproject.toml")
PRODUCTION_PACKAGE = Path("contextual_orchestrator")


def _array_body(section_text: str, key: str) -> str:
    """Return one TOML array body from a bounded project metadata section."""
    match = re.search(
        rf"(?ms)^\s*{re.escape(key)}\s*=\s*\[(?P<body>.*?)\]",
        section_text,
    )
    assert match is not None, f"missing {key!r} dependency array"
    return match.group("body")


def _section(text: str, name: str) -> str:
    """Return one top-level TOML section without requiring a TOML dependency."""
    marker = f"[{name}]"
    start = text.index(marker) + len(marker)
    remainder = text[start:]
    next_section = re.search(r"(?m)^\[[^\n]+\]\s*$", remainder)
    return remainder[: next_section.start()] if next_section else remainder


def test_hypothesis_is_test_only_and_absent_from_production_imports() -> None:
    """Property-testing machinery must not enlarge the credentialed runtime."""
    metadata = PROJECT_METADATA.read_text(encoding="utf-8")
    project_section = _section(metadata, "project")
    optional_section = _section(metadata, "project.optional-dependencies")

    runtime_dependencies = _array_body(project_section, "dependencies")
    test_dependencies = _array_body(optional_section, "test")

    assert "hypothesis" not in runtime_dependencies.lower()
    assert '"hypothesis>=6.100"' in test_dependencies

    imported_roots: set[str] = set()
    for source_path in sorted(PRODUCTION_PACKAGE.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), source_path.as_posix())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.partition(".")[0])

    assert "hypothesis" not in imported_roots
