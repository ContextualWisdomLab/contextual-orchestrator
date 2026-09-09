"""Keep repository quality checks active for every pull-request base."""

from pathlib import Path
import re


def test_quality_workflow_admits_stacked_pull_requests() -> None:
    """Branch and path filters must not omit a valid stacked change."""
    workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/security.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    # Require the canonical unfiltered mapping; actionlint validates YAML syntax.
    assert re.search(r"^  pull_request:\s*\n(?=  \S|\S)", workflow, re.MULTILINE)
    assert "permissions:\n  contents: read\n" in workflow
    assert "pull_request_target:" not in workflow
    assert (
        "group: ${{ github.workflow }}-${{ github.repository }}-"
        "${{ github.event.pull_request.number || github.event.schedule || github.ref }}"
    ) in workflow
    assert "cancel-in-progress: true" in workflow
