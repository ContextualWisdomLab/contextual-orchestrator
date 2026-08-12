"""Reject stale implementation status and credential-authority claims in canonical docs."""

from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
CANONICAL_STATUS_PATHS = (
    "ARCHITECTURE.md",
    "docs/PRD.md",
    "docs/TRACEABILITY.md",
    "docs/TRD.md",
)
CLOSED_UNMERGED_STACKS = (66, 82, 90, 94, 99, 121)


def _read(relative_path: str) -> str:
    """Return one canonical repository document as UTF-8 text."""

    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("pull_request_number", CLOSED_UNMERGED_STACKS)
def test_closed_unmerged_stack_is_superseded_not_active(
    pull_request_number: int,
) -> None:
    """Prevent closed-unmerged work from being promoted as a live implementation."""

    matching_lines = [
        line
        for path in CANONICAL_STATUS_PATHS
        for line in _read(path).splitlines()
        if f"PR #{pull_request_number}" in line
    ]

    assert matching_lines, (
        f"canonical docs must preserve the supersession boundary for PR "
        f"#{pull_request_number}"
    )
    assert all("`active_pr`" not in line for line in matching_lines)
    assert any("`superseded`" in line for line in matching_lines)


def test_reopened_nim_scaffold_is_superseded_without_false_closed_state() -> None:
    """Keep the reopened #115 scaffold outside active authority without calling it closed."""

    traceability = _read("docs/TRACEABILITY.md")
    matching_lines = [
        line for line in traceability.splitlines() if "PR #115" in line
    ]

    assert matching_lines
    assert all("`active_pr`" not in line for line in matching_lines)
    assert any("`superseded`" in line for line in matching_lines)
    assert all("closed-unmerged" not in line for line in matching_lines)
    assert any("open scaffold" in line for line in matching_lines)


def test_configured_postgres_kv_is_fail_closed_not_a_memory_fallback() -> None:
    """Keep canonical config authority aligned with the active #96 composition root."""

    architecture = _read("ARCHITECTURE.md")
    technical_requirements = _read("docs/TRD.md")
    normalized = " ".join(architecture.split())
    combined = " ".join(f"{architecture} {technical_requirements}".split())

    assert (
        "An explicitly configured Postgres KV backend is authoritative and fails "
        "closed with ConfigBackendUnavailableError"
        in normalized
    )
    assert "config and token-count adapters may silently fall back" not in combined
    assert (
        "token counting may deliberately degrade to the documented heuristic"
        in combined.lower()
    )
