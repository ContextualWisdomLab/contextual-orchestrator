import re
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
        "ContextualWisdomLab/.github",
        "Dependency review, Trivy filesystem, OSV, and OpenSSF Scorecard are covered",
        "CodeQL and Python supply-chain evidence stay repo-local",
        "security-events: write",
        "actions/checkout@v7",
        "github/codeql-action/init@v4",
        "github/codeql-action/analyze@v4",
        "python_supply_chain:",
        "actions/setup-python@v6",
        "python -m pip install --require-hashes -r requirements-security-ci.txt",
        "python -m pip install --require-hashes -r requirements.lock",
        "python -m pip install --no-deps -e .",
        "python -m pip_audit -r requirements.lock",
        "cyclonedx-py environment",
        "actions/upload-artifact@v5",
    ]

    for expected_token in expected_tokens:
        assert expected_token in workflow_text

    removed_duplicate_scanners = [
        "actions/dependency-review-action@",
        "aquasecurity/trivy-action@",
        "ossf/scorecard-action@",
        "github/codeql-action/upload-sarif@",
        "id-token: write",
    ]
    for duplicate_scanner in removed_duplicate_scanners:
        assert duplicate_scanner not in workflow_text

    uses_lines = [line.strip() for line in workflow_text.splitlines() if line.strip().startswith("uses:")]
    assert uses_lines
    assert all(re.search(r"@[0-9a-f]{40}(?:\s+#|$)", line) for line in uses_lines)


def test_dependabot_tracks_actions_and_python_dependencies():
    dependabot_text = read_text(".github/dependabot.yml")

    entries = {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"(?ms)^  - package-ecosystem:\s+([^\n]+)\n(.*?)(?=^  - package-ecosystem:|\Z)",
            dependabot_text,
        )
    }

    assert set(entries) == {"github-actions", "pip"}
    for entry in entries.values():
        assert "timezone: Asia/Seoul" in entry
        assert re.search(r"(?m)^    cooldown:\n      default-days: 7$", entry)


def test_review_adr_requires_enforced_exact_head_merge_controls():
    adr_text = read_text("docs/planning/adrs/0004-pr-review-merge-loop.md")
    normalized_adr_text = " ".join(adr_text.split())

    required_controls = [
        "`requiredApprovals >= 1`",
        "`enforce_admins=true`",
        "`reviewDecision=APPROVED`",
        "independent current-head approval",
        "zero active unresolved threads",
        "terminal successful required checks",
        "structured same-head Strix evidence",
        "final re-fetch immediately before",
        "one recorded `verified_head_sha`",
        "the PR head, any check SHA, or the reviewed diff changes",
        "the merge stops and the complete gate is re-evaluated on the new head",
    ]
    for required_control in required_controls:
        assert required_control in normalized_adr_text

    assert (
        "Branch protection and the central scheduler must each reject direct and "
        "auto merge when any control is absent or non-passing."
    ) in normalized_adr_text


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


def test_unit_workflow_uses_the_project_lock_for_git_runtime_dependencies():
    """CI must run the Docker-backed hash-locked test runner."""
    workflow_text = read_text(".github/workflows/tests.yml")
    assert "run: make test" in workflow_text
    assert "scripts/run_hash_locked_tests.sh" in read_text(
        "Makefile"
    )
    installer_text = read_text("scripts/run_hash_locked_tests.sh")
    assert "--target test-runner" in installer_text
    dockerfile_text = read_text("Dockerfile")
    assert "FROM rust:1.97.1-slim-bookworm@sha256:" in dockerfile_text
    assert "apt-get install --no-install-recommends --yes build-essential ca-certificates" in dockerfile_text
    assert "uv python install 3.12" in dockerfile_text
    assert "--with-requirements requirements.lock" in dockerfile_text
    assert "--with \"$1\"" in dockerfile_text


def test_local_full_suite_installs_runtime_and_test_lockfiles():
    """The documented local command must build the native test environment."""
    makefile_text = read_text("Makefile")

    assert "./scripts/run_hash_locked_tests.sh" in makefile_text


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
