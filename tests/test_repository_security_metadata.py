from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_readme_links_deepwiki_and_security_workflow_badges():
    readme_text = read_text("README.md")

    assert "https://deepwiki.com/badge.svg" in readme_text
    assert "https://deepwiki.com/ContextualWisdomLab/contextual-orchestrator" in readme_text
    assert (
        "https://github.com/ContextualWisdomLab/contextual-orchestrator/"
        "actions/workflows/security.yml/badge.svg"
    ) in readme_text
    assert (
        "https://github.com/ContextualWisdomLab/contextual-orchestrator/"
        "actions/workflows/security.yml"
    ) in readme_text


def test_security_workflow_covers_core_repository_security_process():
    workflow_text = read_text(".github/workflows/security.yml")

    expected_tokens = [
        "name: Security",
        "branches: [main]",
        "cron:",
        "workflow_dispatch:",
        "contents: read",
        "security-events: write",
        "id-token: write",
        "actions/checkout@v7",
        "github/codeql-action/init@v4",
        "github/codeql-action/analyze@v4",
        "actions/dependency-review-action@v5",
        "aquasecurity/trivy-action@v0.36.0",
        "github/codeql-action/upload-sarif@v4",
        "ossf/scorecard-action@v2.4.3",
        "publish_results: true",
    ]

    for expected_token in expected_tokens:
        assert expected_token in workflow_text


def test_dependabot_tracks_actions_and_python_dependencies():
    dependabot_text = read_text(".github/dependabot.yml")

    assert "package-ecosystem: github-actions" in dependabot_text
    assert "package-ecosystem: pip" in dependabot_text
    assert "timezone: Asia/Seoul" in dependabot_text


def test_security_policy_documents_reporting_and_automation():
    policy_text = read_text("SECURITY.md")

    assert "GitHub private vulnerability reporting" in policy_text
    assert "CodeQL" in policy_text
    assert "dependency review" in policy_text
    assert "Trivy filesystem scanning" in policy_text
    assert "OpenSSF Scorecard" in policy_text


if __name__ == "__main__":
    test_readme_links_deepwiki_and_security_workflow_badges()
    test_security_workflow_covers_core_repository_security_process()
    test_dependabot_tracks_actions_and_python_dependencies()
    test_security_policy_documents_reporting_and_automation()
    print("ok")
