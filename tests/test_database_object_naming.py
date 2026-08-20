"""Regression checks for descriptive application-owned database identifiers."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CREATE_TABLE_PATTERN = re.compile(
    r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _application_sql_sources() -> list[Path]:
    """Return production SQL-bearing files, excluding test migration fixtures."""
    return sorted(
        [* (ROOT / "contextual_orchestrator").rglob("*.py"),
         * (ROOT / "docs").glob("*.sql")]
    )


def test_application_database_objects_use_multi_word_names() -> None:
    """Prevent new single-word tables from bypassing the naming policy."""
    violations: list[str] = []
    for path in _application_sql_sources():
        text = path.read_text(encoding="utf-8")
        for match in CREATE_TABLE_PATTERN.finditer(text):
            object_name = match.group(1)
            if len(object_name.split("_")) < 2:
                violations.append(f"{path.relative_to(ROOT)}:{object_name}")
    assert violations == []
