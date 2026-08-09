"""Machine-check the canonical product and architecture documentation graph."""

from pathlib import Path
import re
import tomllib


ROOT_DIR = Path(__file__).resolve().parents[1]

STATUS_VOCABULARY = {
    "implemented_on_protected_main",
    "active_pr",
    "accepted_architecture",
    "planned",
    "research_only",
    "superseded",
    "out_of_scope",
}

ADR_FILES = [
    "0001-route-conduct-test-time-compute.md",
    "0002-provider-neutral-transport-trust.md",
    "0003-workflow-access-and-reasoning-control.md",
    "0004-kv-credential-bootstrap.md",
    "0005-sync-batch-pg-llm-batch.md",
    "0006-honest-cost-and-benchmark-evidence.md",
    "0007-free-first-fallback.md",
    "0008-state-persistence-and-retention.md",
    "0009-purpose-bound-pii-protection.md",
    "0010-independent-review-and-evidence.md",
    "0011-release-coverage-and-provenance.md",
    "0012-standalone-and-cwl-boundary.md",
    "0013-database-naming-and-migration.md",
    "0014-scientific-computation-ownership.md",
    "0015-provider-egress-response-trust.md",
    "0016-complete-coverage-docstrings.md",
]

REQUIRED_FILES = [
    "ARCHITECTURE.md",
    "docs/README.md",
    "docs/PRD.md",
    "docs/TRD.md",
    "docs/ERD.md",
    "docs/UML.md",
    "docs/THREAT_MODEL.md",
    "docs/TEST_STRATEGY.md",
    "docs/OPERABILITY.md",
    "docs/INCIDENT_RUNBOOK.md",
    "docs/TRACEABILITY.md",
    "docs/REFERENCES.md",
    "docs/adr/README.md",
    "SECURITY.md",
] + [f"docs/adr/{name}" for name in ADR_FILES]

ADR_SECTIONS = [
    "Context",
    "decision drivers",
    "alternatives",
    "## Decision",
    "## Consequences",
    "Failure and recovery",
    "Security, privacy, and governance",
    "Compatibility and migration",
    "Verification and acceptance",
    "Rollback",
    "supersession",
]


def read_text(relative_path: str) -> str:
    """Return one repository file as UTF-8 text."""

    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def canonical_text() -> str:
    """Return durable canonical documents without the dated evidence appendix."""

    paths = [
        "ARCHITECTURE.md",
        "docs/README.md",
        "docs/PRD.md",
        "docs/TRD.md",
        "docs/ERD.md",
        "docs/UML.md",
        "docs/THREAT_MODEL.md",
        "docs/TEST_STRATEGY.md",
        "docs/OPERABILITY.md",
        "docs/INCIDENT_RUNBOOK.md",
        "docs/REFERENCES.md",
    ] + [f"docs/adr/{name}" for name in ADR_FILES]
    return "\n".join(read_text(path) for path in paths)


def test_required_canonical_files_are_present_and_discoverable():
    """Require the canonical graph and a README entry point."""

    missing = [path for path in REQUIRED_FILES if not (ROOT_DIR / path).is_file()]
    assert missing == []

    index_text = read_text("docs/README.md")
    readme_text = read_text("README.md")
    for path in (
        "PRD.md",
        "TRD.md",
        "ERD.md",
        "UML.md",
        "adr/README.md",
        "THREAT_MODEL.md",
        "TEST_STRATEGY.md",
        "OPERABILITY.md",
        "INCIDENT_RUNBOOK.md",
        "TRACEABILITY.md",
        "REFERENCES.md",
    ):
        assert path in index_text
    assert "docs/README.md" in readme_text


def test_status_vocabulary_is_complete_and_shipped_claims_are_qualified():
    """Keep shipped, proposed, research, and external claims distinguishable."""

    index_text = read_text("docs/README.md")
    for status in STATUS_VOCABULARY:
        assert f"`{status}`" in index_text

    product_text = read_text("docs/PRD.md")
    assert "Capability status" in product_text
    for status in ("implemented_on_protected_main", "active_pr", "planned", "out_of_scope"):
        assert f"`{status}`" in product_text
    assert "does not claim certification" in canonical_text().lower()


def test_adr_index_and_required_decision_sections_are_consistent():
    """Require every minimum decision to be indexed, status-bearing, and recoverable."""

    index_text = read_text("docs/adr/README.md")
    for filename in ADR_FILES:
        assert filename in index_text
        body = read_text(f"docs/adr/{filename}")
        assert any(f"`{status}`" in body.split("## Context", 1)[0] for status in STATUS_VOCABULARY)
        normalized = body.lower()
        for section in ADR_SECTIONS:
            assert section.lower() in normalized, f"{filename} lacks {section}"


def test_mermaid_blocks_are_balanced_and_cover_required_flows():
    """Require parseable block boundaries and the named runtime/deployment flows."""

    for path in ("ARCHITECTURE.md", "docs/UML.md", "docs/ERD.md", "docs/TRACEABILITY.md"):
        text = read_text(path)
        assert text.count("```mermaid") > 0
        assert text.count("```") % 2 == 0

    uml_text = read_text("docs/UML.md").lower()
    for term in (
        "component topology",
        "route sequence",
        "conduct sequence",
        "access lists",
        "credential bootstrap",
        "provider failover and circuit breaker",
        "sync-versus-batch",
        "evidence and merge authority",
        "deployment topology",
        "degraded-mode topology",
    ):
        assert term in uml_text


def test_canonical_names_match_live_modules_api_and_data_ownership():
    """Catch stale class names, invented endpoints, and ambiguous entity ownership."""

    architecture_text = read_text("ARCHITECTURE.md")
    for module_name in (
        "orchestrator.py",
        "server.py",
        "credentials.py",
        "cost_ledger.py",
        "batch_routing.py",
        "cost_router.py",
        "token_counting.py",
    ):
        assert (ROOT_DIR / "contextual_orchestrator" / module_name).is_file()
        assert f"`{module_name}`" in architecture_text
    assert "contextual_orchestrator.orchestrator.Agent" not in canonical_text()
    assert "contextual_orchestrator.orchestrator.Orchestrator" not in canonical_text()

    api_source = read_text("contextual_orchestrator/api_contract.py")
    server_source = read_text("contextual_orchestrator/server.py")
    trd_text = read_text("docs/TRD.md")
    assert "/v1/chat/completions" in server_source
    assert "/v1/chat/completions" in trd_text
    for endpoint in ("/api/v1/workflow_runs", "/api/v1/batch_routing_jobs"):
        assert endpoint in api_source
        assert endpoint in trd_text

    erd_text = read_text("docs/ERD.md")
    for entity_name in (
        "model_agent",
        "workflow_run",
        "workflow_step",
        "step_dependency",
        "access_grant",
        "provider_credential",
        "credential_backend",
        "cost_ledger_entry",
        "routing_decision",
        "batch_request",
        "batch_result",
        "audit_event",
        "fallback_candidate",
        "check_evidence",
        "release_evidence",
    ):
        assert f"`{entity_name}`" in erd_text
    for ownership in ("persisted_runtime", "in_memory", "external_owned", "accepted_target", "active_pr"):
        assert f"`{ownership}`" in erd_text


def test_runtime_version_credentials_and_authority_boundaries_are_current():
    """Tie documentation claims to package metadata and current credential/host boundaries."""

    project = tomllib.loads(read_text("pyproject.toml"))["project"]
    trd_text = read_text("docs/TRD.md")
    assert project["version"] in trd_text
    assert project["requires-python"] in trd_text

    text = canonical_text()
    for term in (
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "environment variables are bootstrap transport",
        "independent review",
        "standalone",
        "host owns",
        "pg-llm-batch",
        "DNS",
        "redirect",
        "proxy",
        "response",
        "purpose",
        "retention",
        "SBOM",
    ):
        assert term.lower() in text.lower()


def test_references_and_volatile_evidence_are_separated():
    """Keep standards/research durable while confining revision IDs to the dated audit."""

    references = read_text("docs/REFERENCES.md")
    for term in ("Fugu", "Conductor", "TRINITY", "RFC 8259", "NIST", "ISO/IEC"):
        assert term in references

    durable = canonical_text()
    sha_pattern = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
    assert sha_pattern.search(durable) is None
    assert sha_pattern.search(read_text("docs/TRACEABILITY.md")) is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run with pytest so every documentation contract executes.")
