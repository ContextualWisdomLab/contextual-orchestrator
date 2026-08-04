"""Regression tests for the pull-request workflow credential boundary.

Pull-request heads are untrusted input. A workflow may inspect or test that code,
but it must not give the same job an OpenID Connect token that can be exchanged
for repository-writing credentials. Publication belongs to a separately trusted
workflow whose executable source is not selected by the pull-request branch.
"""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TESTS_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"
TEMPORARY_REPAIR_WORKFLOW_PATHS = (
    REPOSITORY_ROOT / ".github" / "workflows" / "nim-source-repair.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "nim-source-repair-trigger.yml",
)


def test_pull_request_tests_cannot_exchange_repository_write_credentials() -> None:
    """Keep pull-request test execution read-only and unable to mint write tokens."""
    workflow_text = TESTS_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pull_request:" in workflow_text
    assert "id-token: write" not in workflow_text
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in workflow_text
    assert "exchange_github_app_token" not in workflow_text
    assert "git push origin" not in workflow_text
    assert all(not workflow_path.exists() for workflow_path in TEMPORARY_REPAIR_WORKFLOW_PATHS)
