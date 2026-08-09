"""Machine-check the canonical product and architecture documentation graph."""

from pathlib import Path
import re


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
    "docs/UML.md",
    "docs/ERD.md",
    "docs/TRACEABILITY.md",
    "docs/THREAT_MODEL.md",
    "docs/TEST_STRATEGY.md",
    "docs/OPERABILITY.md",
    "docs/INCIDENT_RUNBOOK.md",
    "docs/REFERENCES.md",
    "docs/adr/README.md",
    "SECURITY.md",
] + [f"docs/adr/{filename}" for filename in ADR_FILES]

ADR_HEADINGS = [
    "## Status",
    "## Context and decision drivers",
    "## Considered alternatives",
    "## Decision",
    "## Consequences",
    "## Failure and recovery",
    "## Security, privacy, and governance impact",
    "## Compatibility and migration",
    "## Verification and acceptance",
    "## Rollback and supersession",
    "## References",
]

CANONICAL_FILES = [
    "ARCHITECTURE.md",
    "docs/README.md",
    "docs/PRD.md",
    "docs/TRD.md",
    "docs/UML.md",
    "docs/ERD.md",
    "docs/THREAT_MODEL.md",
    "docs/TEST_STRATEGY.md",
    "docs/OPERABILITY.md",
    "docs/INCIDENT_RUNBOOK.md",
    "docs/REFERENCES.md",
    "docs/adr/README.md",
] + [f"docs/adr/{filename}" for filename in ADR_FILES]

LINK_CHECK_FILES = CANONICAL_FILES + [
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "SECURITY.md",
    "docs/TRACEABILITY.md",
    "docs/architecture.md",
    "docs/fuzzing.md",
    "docs/papers/README.md",
]


def read_text(relative_path: str) -> str:
    """Return one repository file as UTF-8 text."""

    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def canonical_text() -> str:
    """Return durable canonical documents without the dated evidence appendix."""

    return "\n".join(read_text(path) for path in CANONICAL_FILES)


def test_required_canonical_files_are_present_and_indexed() -> None:
    """Require one discoverable authority for every requested document family."""

    missing = [path for path in REQUIRED_FILES if not (ROOT_DIR / path).is_file()]
    assert missing == []

    index_text = read_text("docs/README.md")
    for link in (
        "[PRD](PRD.md)",
        "[TRD](TRD.md)",
        "[Architecture](../ARCHITECTURE.md)",
        "[UML](UML.md)",
        "[ERD](ERD.md)",
        "[ADR index](adr/README.md)",
        "[Traceability](TRACEABILITY.md)",
        "[Threat model](THREAT_MODEL.md)",
        "[Test strategy](TEST_STRATEGY.md)",
        "[Operability](OPERABILITY.md)",
        "[Incident runbook](INCIDENT_RUNBOOK.md)",
        "[References](REFERENCES.md)",
    ):
        assert index_text.count(link) == 1
    assert "[docs/README.md](docs/README.md)" in read_text("README.md")


def test_status_vocabulary_product_scope_and_prompt_continuity_are_explicit() -> None:
    """Keep shipped/proposed work distinct and prevent audit-only early stops."""

    index_text = read_text("docs/README.md")
    for status in STATUS_VOCABULARY:
        assert f"`{status}`" in index_text

    product_text = read_text("docs/PRD.md")
    for requirement_id in range(1, 11):
        assert f"PRD-{requirement_id:03d}" in product_text
    for status in (
        "implemented_on_protected_main",
        "active_pr",
        "planned",
        "out_of_scope",
    ):
        assert f"`{status}`" in product_text

    prompt_text = read_text("AGENTS.md")
    assert "## Execution continuity" in prompt_text
    assert "intermediate work" in prompt_text


def test_adr_index_and_schema_are_consistent() -> None:
    """Require every decision to be uniquely indexed, status-bearing, and recoverable."""

    index_text = read_text("docs/adr/README.md")
    numbers = []
    for filename in ADR_FILES:
        number = filename.split("-", 1)[0]
        numbers.append(number)
        assert index_text.count(f"({filename})") == 1
        body = read_text(f"docs/adr/{filename}")
        for heading in ADR_HEADINGS:
            assert heading in body, f"{filename} lacks {heading}"
        status_section = body.split("## Status", 1)[1].split("\n## ", 1)[0]
        assert any(f"`{status}`" in status_section for status in STATUS_VOCABULARY)
    assert len(numbers) == len(set(numbers))


def test_mermaid_blocks_are_balanced_and_cover_required_views() -> None:
    """Require source-controlled component, sequence, state, and ER views."""

    diagram_sources = {
        "ARCHITECTURE.md": "flowchart",
        "docs/UML.md": "sequenceDiagram",
        "docs/ERD.md": "erDiagram",
        "docs/TRACEABILITY.md": "flowchart",
    }
    all_diagrams = []
    for path, required_type in diagram_sources.items():
        source = read_text(path)
        blocks = re.findall(r"```mermaid\s*\n(.*?)```", source, flags=re.DOTALL)
        assert len(blocks) == source.count("```mermaid"), path
        assert any(block.lstrip().startswith(required_type) for block in blocks), path
        all_diagrams.extend(blocks)
    assert any(block.lstrip().startswith("stateDiagram-v2") for block in all_diagrams)


def test_live_names_routes_and_physical_data_objects_are_not_stale() -> None:
    """Tie architecture names and ERD claims to protected-main source strings."""

    durable_text = canonical_text()
    assert "TaskOrchestrator" in durable_text
    assert "CostRoutingCoordinator" in durable_text
    assert "contextual_orchestrator.orchestrator.Agent" not in durable_text
    assert "contextual_orchestrator.orchestrator.Orchestrator" not in durable_text
    assert "Orchestrator.route_once" not in durable_text

    server_source = read_text("contextual_orchestrator/server.py")
    trd_text = read_text("docs/TRD.md")
    for endpoint in (
        "/healthz",
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/batch/embeddings",
        "/api/v1/batch_routing_jobs",
        "/api/v1/workflow_runs",
    ):
        assert endpoint in server_source
        assert endpoint in trd_text

    physical_sources = "\n".join(
        read_text(path)
        for path in (
            "contextual_orchestrator/orchestrator.py",
            "contextual_orchestrator/credentials.py",
            "contextual_orchestrator/cost_ledger.py",
        )
    )
    erd_text = read_text("docs/ERD.md")
    for object_name in (
        "agent_pool",
        "records",
        "provider_credentials",
        "cost_attribution_dimensions",
        "llm_price_entries",
        "llm_usage_records",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {object_name}" in physical_sources
        assert f"`{object_name}`" in erd_text
    for classification in (
        "persisted_runtime",
        "in_memory",
        "external_owned",
        "accepted_target",
        "active_pr",
    ):
        assert f"`{classification}`" in erd_text


def test_current_evidence_gaps_are_not_promoted_into_capabilities() -> None:
    """Keep cost, stream, batch, OpenAPI, and provider-selection gaps explicit."""

    text = canonical_text()
    for term in (
        "two unsynchronized cost authorities",
        "missing price as zero",
        "sql price table is dormant",
        "passthrough",
        "route streaming",
        "process-local",
        "openapi",
        "cheapest_upstream()",
        "not learned, price-aware, or load-balanced",
    ):
        assert term in text.lower()


def test_database_naming_exception_is_bounded() -> None:
    """Do not hide the one-word legacy table or normalize future ambiguity."""

    erd_text = read_text("docs/ERD.md")
    adr_text = read_text("docs/adr/0013-database-naming-and-migration.md")
    for text in (erd_text, adr_text):
        assert "two-or-more-word snake_case" in text
        assert "`records`" in text
        assert "technical debt" in text
        assert "runtime_records" in text


def test_local_markdown_links_resolve() -> None:
    """Reject broken relative links in the canonical graph."""

    link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    broken = []
    for relative_path in LINK_CHECK_FILES:
        source_path = ROOT_DIR / relative_path
        for raw_target in link_pattern.findall(read_text(relative_path)):
            target = raw_target.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith(("#", "/")):
                continue
            resolved = (source_path.parent / target).resolve()
            try:
                resolved.relative_to(ROOT_DIR.resolve())
            except ValueError:
                broken.append((relative_path, raw_target))
                continue
            if not resolved.exists():
                broken.append((relative_path, raw_target))
    assert broken == []


def test_references_licensing_and_volatile_evidence_are_separated() -> None:
    """Keep research, licensing, and revision evidence under distinct authority."""

    references = read_text("docs/REFERENCES.md")
    for term in (
        "Fugu",
        "Conductor",
        "TRINITY",
        "RFC 8259",
        "NIST SP 800-218A",
        "42001:2023",
        "OpenAPI Specification",
        "3.1.0",
        "CSAP",
        "non-exclusive grant to arXiv",
    ):
        assert term in references

    assert list((ROOT_DIR / "docs" / "papers").glob("*.pdf")) == []
    paper_index = read_text("docs/papers/README.md")
    assert "does not itself grant downstream" in paper_index
    assert "CC BY-NC-ND 4.0" in paper_index

    sha_pattern = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
    assert sha_pattern.search(canonical_text()) is None
    assert sha_pattern.search(read_text("docs/TRACEABILITY.md")) is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run with pytest so every documentation contract executes.")
