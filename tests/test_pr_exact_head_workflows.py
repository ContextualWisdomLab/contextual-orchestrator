"""Contracts that prevent local pull-request workflows from testing stale or synthetic heads."""

from __future__ import annotations

from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXACT_HEAD_REF = (
    "ref: ${{ github.event_name == 'pull_request' "
    "&& github.event.pull_request.head.sha || github.sha }}"
)
WORKFLOW_PATHS = (
    Path(".github/workflows/tests.yml"),
    Path(".github/workflows/fuzz.yml"),
    Path(".github/workflows/security.yml"),
)


@pytest.mark.parametrize("relative_path", WORKFLOW_PATHS)
def test_pull_request_workflows_cover_stacked_exact_heads(relative_path: Path) -> None:
    """Require all PR bases to run while every checkout selects the contributor head."""
    workflow = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
    checkout_count = workflow.count("uses: actions/checkout@")
    assert checkout_count > 0
    assert "pull_request:\n    branches: [main]" not in workflow
    assert workflow.count(EXACT_HEAD_REF) == checkout_count
    assert workflow.count("persist-credentials: false") >= checkout_count
