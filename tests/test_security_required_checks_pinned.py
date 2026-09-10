"""Pin the Security-workflow job names that branch protection requires.

Context: PR #1054 renamed the Security-workflow jobs while ``main`` branch
protection still required the pre-rename check names (issue #1079). GitHub
matches required contexts by check-run name, so every ``base=main`` PR stayed
``blocked`` forever and merges went around protection instead of through it.

The three names below are required-status-check contexts on ``main``. Renaming
a job in ``.github/workflows/security.yml`` without the matching owner-side
protection update re-creates #1079, so this test fails first on any rename.
"""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SECURITY_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/security.yml"

# Exact ``name:`` values of the three jobs. Kept in sync with the ``main``
# branch-protection required contexts by the repository owner.
REQUIRED_CHECK_NAMES = (
    "Tests and package quality",
    "Property and coverage-guided fuzzing",
    "CodeQL, supply chain, and SBOM",
)

# Pre-#1054 check names. Nothing may produce them anymore; protection must not
# require them either (see issue #1079).
RETIRED_CHECK_NAMES = (
    "Hypothesis property tests",
    "Atheris coverage-guided",
    "CodeQL analysis",
    "Python supply chain",
)


def _workflow_text() -> str:
    return SECURITY_WORKFLOW.read_text(encoding="utf-8")


def test_required_check_names_are_declared_exactly_once() -> None:
    """Each protection-required context must come from exactly one job name."""
    workflow = _workflow_text()
    for name in REQUIRED_CHECK_NAMES:
        assert workflow.count(f"name: {name}") == 1, (
            f"expected exactly one job named {name!r} in security.yml "
            "(rename requires the owner protection update from #1079)"
        )


def test_retired_check_names_are_absent() -> None:
    """Pre-#1054 job names must not reappear in the workflow."""
    workflow = _workflow_text()
    for name in RETIRED_CHECK_NAMES:
        assert f"name: {name}" not in workflow, (
            f"retired check name {name!r} found in security.yml"
        )


if __name__ == "__main__":
    test_required_check_names_are_declared_exactly_once()
    test_retired_check_names_are_absent()
    print("2 passed")
