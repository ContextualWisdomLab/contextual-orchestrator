"""Contracts that prevent pull-request workflows from testing synthetic merges."""

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
def test_pull_request_workflows_checkout_every_exact_head(relative_path: Path) -> None:
    """Require every local checkout to select the contributor head on PR events."""
    workflow = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
    checkout_count = workflow.count("uses: actions/checkout@")
    assert checkout_count > 0
    assert workflow.count(EXACT_HEAD_REF) == checkout_count
    assert workflow.count("persist-credentials: false") >= checkout_count
