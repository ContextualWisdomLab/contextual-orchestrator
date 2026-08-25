"""Regression checks for descriptive application-owned database identifiers."""

from __future__ import annotations

from pathlib import Path
import re

from contextual_orchestrator.conventions import is_two_word_snake_case


ROOT = Path(__file__).resolve().parents[1]
SQL_IDENTIFIER = r'(?:[A-Za-z][A-Za-z0-9_]*|"[^"]+"|`[^`]+`|\[[^\]]+\])'
CREATE_OBJECT_PATTERN = re.compile(
    r"(?:CREATE\s+(?:(?:UNIQUE\s+)?(?:TABLE|INDEX)|VIEW|SEQUENCE)"
    rf"(?:\s+IF\s+NOT\s+EXISTS)?|CONSTRAINT)\s+(?:{SQL_IDENTIFIER}\.)*"
    rf"(?P<object_name>{SQL_IDENTIFIER})",
    re.IGNORECASE,
)
SQL_CONTROL_WORDS = {"IF", "NOT", "EXISTS"}


def _normalize_sql_identifier(value: str) -> str:
    """Return an SQL identifier without supported quoting delimiters."""
    if len(value) >= 2 and ((value[0], value[-1]) in {("\"", "\""), ("`", "`"), ("[", "]")}):
        return value[1:-1]
    return value


def _extract_object_names(text: str) -> list[str]:
    """Extract final object components from supported SQL declaration forms."""
    return [_normalize_sql_identifier(match.group("object_name")) for match in CREATE_OBJECT_PATTERN.finditer(text)]


def _application_sql_sources() -> list[Path]:
    """Return production SQL-bearing files, excluding test migration fixtures."""
    return sorted(
        [*(ROOT / "contextual_orchestrator").rglob("*.py"), *(ROOT / "docs").glob("*.sql")]
    )


def test_application_database_objects_use_descriptive_names() -> None:
    """Keep application-owned tables, indexes, views, and constraints consistent."""
    violations: list[str] = []
    for path in _application_sql_sources():
        text = path.read_text(encoding="utf-8")
        for object_name in _extract_object_names(text):
            # Dynamic SQL may interpolate the identifier after this literal
            # prefix; there is no object name to validate in the source text.
            if object_name.upper() in SQL_CONTROL_WORDS:
                continue
            if not is_two_word_snake_case(object_name):
                violations.append(f"{path.relative_to(ROOT)}:{object_name}")
    assert violations == []


def test_descriptive_name_pattern_rejects_single_word_and_mixed_case() -> None:
    """Prove the gate rejects the bypasses that motivated the review finding."""
    assert is_two_word_snake_case("agent_pool")
    assert not is_two_word_snake_case("records")
    assert not is_two_word_snake_case("Agent_Pool")
    assert not is_two_word_snake_case("agent_")


def test_object_pattern_extracts_quoted_qualified_and_constraint_identifiers() -> None:
    """Keep SQL naming checks effective for common identifier spellings."""
    sql = """
    CREATE TABLE "tenant_schema"."agent_pool";
    CREATE UNIQUE INDEX IF NOT EXISTS `tenant_schema`.`workflow_step_retention_idx`;
    CREATE VIEW [workflow_run_safe_view] AS SELECT 1;
    CONSTRAINT "workflow_run_preview_limit" CHECK (1 = 1);
    """

    assert _extract_object_names(sql) == [
        "agent_pool",
        "workflow_step_retention_idx",
        "workflow_run_safe_view",
        "workflow_run_preview_limit",
    ]


def test_each_sql_object_declaration_checks_valid_and_invalid_names() -> None:
    """Exercise every supported declaration branch against the canonical rule."""
    declarations = (
        ("CREATE TABLE agent_pool", "CREATE TABLE records"),
        ("CREATE UNIQUE INDEX agent_pool_lookup", "CREATE UNIQUE INDEX records"),
        ("CREATE INDEX IF NOT EXISTS agent_pool_lookup", "CREATE INDEX IF NOT EXISTS records"),
        ("CREATE VIEW workflow_run_safe_view", "CREATE VIEW records"),
        ("CREATE SEQUENCE workflow_run_sequence", "CREATE SEQUENCE records"),
        ("CONSTRAINT workflow_run_preview_limit CHECK (1 = 1)", "CONSTRAINT records CHECK (1 = 1)"),
    )
    for declaration, invalid_declaration in declarations:
        valid_match = CREATE_OBJECT_PATTERN.search(declaration)
        assert valid_match is not None
        assert is_two_word_snake_case(_normalize_sql_identifier(valid_match.group("object_name")))

        invalid_match = CREATE_OBJECT_PATTERN.search(invalid_declaration)
        assert invalid_match is not None
        assert not is_two_word_snake_case(_normalize_sql_identifier(invalid_match.group("object_name")))
