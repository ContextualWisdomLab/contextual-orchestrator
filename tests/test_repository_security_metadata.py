from pathlib import Path
import re


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
        "python_supply_chain:",
        "actions/setup-python@v6",
        "python -m pip install --require-hashes -r requirements-security-ci.txt",
        "python -m pip install --require-hashes -r requirements.lock",
        "python -m pip install --no-deps -e .",
        "python -m pip_audit -r requirements.lock",
        "cyclonedx-py environment",
        "actions/upload-artifact@v5",
        "aquasecurity/trivy-action@v0.36.0",
        "github/codeql-action/upload-sarif@v4",
        "ossf/scorecard-action@v2.4.3",
        "publish_results: true",
    ]

    for expected_token in expected_tokens:
        assert expected_token in workflow_text

    uses_lines = [line.strip() for line in workflow_text.splitlines() if line.strip().startswith("uses:")]
    assert uses_lines
    assert all(re.search(r"@[0-9a-f]{40}(?:\s+#|$)", line) for line in uses_lines)


def test_dependabot_tracks_actions_and_python_dependencies():
    dependabot_text = read_text(".github/dependabot.yml")

    assert "package-ecosystem: github-actions" in dependabot_text
    assert "package-ecosystem: pip" in dependabot_text
    assert "timezone: Asia/Seoul" in dependabot_text


def test_codeowners_requires_repository_owner_review():
    codeowners_text = read_text(".github/CODEOWNERS")

    assert "* @seonghobae" in codeowners_text


def test_security_policy_documents_reporting_and_automation():
    policy_text = read_text("SECURITY.md")

    assert "GitHub private vulnerability reporting" in policy_text
    assert (
        "https://github.com/ContextualWisdomLab/contextual-orchestrator/"
        "security/advisories/new"
    ) in policy_text
    assert "CodeQL" in policy_text
    assert "dependency review" in policy_text
    assert "pip-audit" in policy_text
    assert "requirements.lock" in policy_text
    assert "requirements-security-ci.txt" in policy_text
    assert "CycloneDX SBOM" in policy_text
    assert "Trivy filesystem scanning" in policy_text
    assert "OpenSSF Scorecard" in policy_text
    assert "pinned to reviewed commit SHAs or hash-locked package requirements" in policy_text


def test_database_design_avoids_plaintext_prompt_output_storage():
    database_text = read_text("docs/database_design.sql")

    assert "prompt_ciphertext bytea not null" in database_text
    assert "answer_ciphertext bytea not null" in database_text
    assert "output_ciphertext bytea not null" in database_text
    assert "retention_expires_at timestamptz not null" in database_text
    assert "purge_expired_orchestration_data" in database_text
    assert "workflow_run_safe_view" in database_text
    assert "prompt_text text not null" not in database_text
    assert "answer_text text not null" not in database_text
    assert "output_text text not null" not in database_text


def test_python_lockfile_uses_hash_pinning():
    lock_text = read_text("requirements.lock")

    assert "pip-compile" in lock_text
    assert "--hash=sha256:" in lock_text
    assert "fastapi==" in lock_text
    assert "uvicorn==" in lock_text
    assert "sqlalchemy==" in lock_text


def test_security_tool_lockfile_uses_hash_pinning():
    lock_text = read_text("requirements-security-ci.txt")

    assert "uv pip compile" in lock_text
    assert "--hash=sha256:" in lock_text
    assert "pip-audit==2.10.1" in lock_text
    assert "cyclonedx-bom==7.3.0" in lock_text


if __name__ == "__main__":  # pragma: no cover
    test_readme_links_deepwiki_and_security_workflow_badges()
    test_security_workflow_covers_core_repository_security_process()
    test_dependabot_tracks_actions_and_python_dependencies()
    test_codeowners_requires_repository_owner_review()
    test_security_policy_documents_reporting_and_automation()
    test_database_design_avoids_plaintext_prompt_output_storage()
    test_python_lockfile_uses_hash_pinning()
    test_security_tool_lockfile_uses_hash_pinning()
    print("ok")
