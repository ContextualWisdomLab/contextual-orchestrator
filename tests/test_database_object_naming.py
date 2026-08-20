"""Regression checks for descriptive application-owned database identifiers."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SQL_IDENTIFIER = r"(?:[A-Za-z][A-Za-z0-9_]*|\"[^\"]+\"|`[^`]+`|\[[^\]]+\])"
CREATE_OBJECT_PATTERN = re.compile(
    rf"(?:CREATE\s+(?:(?:UNIQUE\s+)?(?:TABLE|INDEX)|VIEW|SEQUENCE)"
    rf"(?:\s+IF\s+NOT\s+EXISTS)?|CONSTRAINT)\s+"
    rf"({SQL_IDENTIFIER}(?:\s*\.\s*{SQL_IDENTIFIER})?)",
    re.IGNORECASE,
)
DESCRIPTIVE_SNAKE_CASE_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+\Z")
SQL_CONTROL_WORDS = {"IF", "NOT", "EXISTS"}


def _unquote_object_name(identifier: str) -> str:
    """Return the final object segment from plain, quoted, or qualified SQL."""
    object_name = re.split(r"\s*\.\s*", identifier)[-1]
    if len(object_name) >= 2 and object_name[0] == object_name[-1] and object_name[0] in {'"', '`'}:
        return object_name[1:-1]
    if object_name.startswith("[") and object_name.endswith("]"):
        return object_name[1:-1]
    return object_name


def _application_sql_sources() -> list[Path]:
    """Return production SQL-bearing files, excluding test migration fixtures."""
    return sorted(
        [* (ROOT / "contextual_orchestrator").rglob("*.py"),
         * (ROOT / "docs").glob("*.sql")]
    )


def test_application_database_objects_use_descriptive_names() -> None:
    """Keep application-owned tables, indexes, views, and constraints consistent."""
    violations: list[str] = []
    for path in _application_sql_sources():
        text = path.read_text(encoding="utf-8")
        for match in CREATE_OBJECT_PATTERN.finditer(text):
            object_name = _unquote_object_name(match.group(1))
            # Dynamic SQL may interpolate the identifier after this literal
            # prefix; there is no object name to validate in the source text.
            if object_name.upper() in SQL_CONTROL_WORDS:
                continue
            if not DESCRIPTIVE_SNAKE_CASE_PATTERN.fullmatch(object_name):
                violations.append(f"{path.relative_to(ROOT)}:{object_name}")
    assert violations == []


def test_descriptive_name_pattern_rejects_single_word_and_mixed_case() -> None:
    """Prove the gate rejects the bypasses that motivated the review finding."""
    assert DESCRIPTIVE_SNAKE_CASE_PATTERN.fullmatch("agent_pool")
    assert not DESCRIPTIVE_SNAKE_CASE_PATTERN.fullmatch("records")
    assert not DESCRIPTIVE_SNAKE_CASE_PATTERN.fullmatch("Agent_Pool")
    assert not DESCRIPTIVE_SNAKE_CASE_PATTERN.fullmatch("agent_")


def test_object_name_extractor_handles_quoted_qualified_and_constraint_forms() -> None:
    """Cover SQL identifier spellings the naming gate must inspect equally."""
    examples = {
        'CREATE TABLE "tenant_schema"."agent_pool"': "agent_pool",
        "CREATE UNIQUE INDEX `agent_pool_lookup` ON agent_pool": "agent_pool_lookup",
        "CREATE VIEW [workflow_run_safe_view] AS SELECT 1": "workflow_run_safe_view",
        "CONSTRAINT \"workflow_run_preview_limit\" CHECK (1 = 1)": "workflow_run_preview_limit",
    }
    for sql, expected in examples.items():
        match = CREATE_OBJECT_PATTERN.search(sql)
        assert match is not None
        assert _unquote_object_name(match.group(1)) == expected
