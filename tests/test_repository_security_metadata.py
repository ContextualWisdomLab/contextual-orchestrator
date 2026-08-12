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


def test_security_policy_documents_coordinated_disclosure_lifecycle():
    policy_text = read_text("SECURITY.md")
    doctoring_text = read_text("docs/doctoring/security-disclosure-lifecycle.md")

    def section(document, heading):
        start = document.index(heading) + len(heading)
        end = document.find("\n## ", start)
        return document[start:] if end == -1 else document[start:end]

    required_policy_tokens = [
        "## Supported Versions",
        "## Scope",
        "## Reporting a Vulnerability",
        "## Coordinated Disclosure Lifecycle",
        "## Safe Harbor and Research Boundaries",
        "## Advisory and Release Evidence",
        "latest supported release",
        "GitHub Security Advisory",
        "acknowledgement target",
        "not a remediation SLA",
        "CVE",
        "Reporter credit",
        "public issue",
        "Do not include exploit details",
        "ISO/IEC 29147:2018",
        "ISO/IEC 30111:2019",
    ]
    for token in required_policy_tokens:
        assert token in policy_text

    supported_versions = section(policy_text, "## Supported Versions")
    assert "No stable release currently exists" in supported_versions
    assert "`main` is not a supported release" in supported_versions
    assert "version or release line" in supported_versions

    reporting = section(policy_text, "## Reporting a Vulnerability")
    assert "Remove credentials, personal data" in reporting
    assert "Do not include exploit details, secrets, personal data" in reporting

    lifecycle = section(policy_text, "## Coordinated Disclosure Lifecycle")
    lifecycle_stages = (
        "Receive and acknowledge",
        "Validate and scope",
        "Remediate and verify",
        "Coordinate release",
        "Publish evidence",
        "Learn and prevent recurrence",
    )
    lifecycle_positions = [lifecycle.index(stage) for stage in lifecycle_stages]
    assert lifecycle_positions == sorted(lifecycle_positions)

    safe_harbor = section(policy_text, "## Safe Harbor and Research Boundaries")
    for prohibited_activity in (
        "denial-of-service testing",
        "social engineering",
        "credential stuffing",
        "destructive testing",
        "high-volume automated probing",
    ):
        assert prohibited_activity in safe_harbor

    release_evidence = section(policy_text, "## Advisory and Release Evidence")
    canonical_nonpassing_states = (
        "queued",
        "pending",
        "skipped-required",
        "cancelled",
        "failed",
        "absent",
        "stale-head",
        "predecessor-head",
        "author-only",
        "status-only",
        "synthetic-merge-only",
        "rate-limited",
        "infrastructure-only",
    )
    assert "docs/RELEASE_GUIDE.md" in release_evidence
    assert "exact integrated revision" in release_evidence
    for state in canonical_nonpassing_states:
        assert state in release_evidence

    required_doctoring_tokens = [
        "ISO/IEC 29147:2018",
        "ISO/IEC 30111:2019",
        "reviewed and confirmed",
        "GitHub private vulnerability reporting",
        "repository security advisory",
        "NIST SP 800-218 Rev. 1",
        "Initial Public Draft",
        "Harold Booth",
        "Michael Ogata",
        "Karen Kent",
        "Murugiah Souppaya",
        "Donna Dodson",
        "https://doi.org/10.6028/NIST.SP.800-218r1.ipd",
        "APA 7",
    ]
    for token in required_doctoring_tokens:
        assert token in doctoring_text

    doctoring_contract = section(doctoring_text, "## Repository contract")
    assert "docs/RELEASE_GUIDE.md" in doctoring_contract
    assert "exact integrated revision" in doctoring_contract
    for state in canonical_nonpassing_states:
        assert state in doctoring_contract


def test_agent_guidance_preserves_central_review_authority_and_nim_development_key():
    for guidance_path in ("AGENTS.md", "CLAUDE.md"):
        guidance_text = read_text(guidance_path)

        assert "stays on **GitHub Models**" not in guidance_text
        assert "stays on GitHub Models" not in guidance_text
        assert "centrally governed" in guidance_text
        assert "`NVIDIA_NIM_API_KEY`" in guidance_text
        assert "`COPILOT_GITHUB_TOKEN`" in guidance_text


def test_agent_guidance_enforces_writer_lease_and_read_only_dependencies():
    required_tokens = (
        "one writer per repository branch",
        "exact PR head and target blob SHA",
        "read-only dependencies",
        "write-capable agents",
        "stale-head",
    )
    for guidance_path in ("AGENTS.md", "CLAUDE.md"):
        guidance_text = read_text(guidance_path)
        for required_token in required_tokens:
            assert required_token in guidance_text


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
    test_security_policy_documents_coordinated_disclosure_lifecycle()
    test_agent_guidance_preserves_central_review_authority_and_nim_development_key()
    test_agent_guidance_enforces_writer_lease_and_read_only_dependencies()
    test_database_design_avoids_plaintext_prompt_output_storage()
    test_python_lockfile_uses_hash_pinning()
    test_security_tool_lockfile_uses_hash_pinning()
    print("ok")
