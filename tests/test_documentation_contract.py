"""Machine-check the canonical product and architecture documentation graph."""

import ast
import re
from pathlib import Path


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
    "docs/RELEASE_GUIDE.md",
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
    "docs/RELEASE_GUIDE.md",
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

AUDITED_OPEN_PR_NUMBERS = {
    63,
    66,
    69,
    71,
    75,
    82,
    83,
    84,
    90,
    94,
    96,
    99,
    104,
    105,
    107,
}


def read_text(relative_path: str) -> str:
    """Return one repository file as UTF-8 text."""

    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def canonical_text() -> str:
    """Return durable canonical documents without the dated evidence appendix."""

    return "\n".join(read_text(path) for path in CANONICAL_FILES)


def class_method_names(relative_path: str, class_name: str) -> set[str]:
    """Return methods declared directly on one runtime class."""

    tree = ast.parse(read_text(relative_path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"{class_name} is absent from {relative_path}")


def validate_mermaid_subset(block: str, source_path: str) -> None:
    """Parse the Mermaid subset used by the canonical architecture documents."""

    lines = [line.strip() for line in block.splitlines() if line.strip()]
    assert lines, f"{source_path} contains an empty Mermaid block"
    diagram_type, body = lines[0], lines[1:]
    assert body, f"{source_path} contains an empty {diagram_type} diagram"
    for line in body:
        assert line.count('"') % 2 == 0, f"{source_path}: unbalanced quote in {line!r}"

    if diagram_type.startswith("flowchart "):
        assert re.fullmatch(r"flowchart (?:TB|TD|BT|LR|RL)", diagram_type)
        node = r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]+\])?"
        edge = re.compile(
            rf"{node}\s+(?:-->(?:\|[^|]+\|)?|-\..+\.->)\s*{node}"
        )
        subgraph_depth = 0
        for line in body:
            if line.startswith("subgraph "):
                assert re.fullmatch(rf"subgraph {node}", line), (
                    f"{source_path}: unsupported subgraph syntax {line!r}"
                )
                subgraph_depth += 1
            elif line == "end":
                assert subgraph_depth > 0, f"{source_path}: unmatched flowchart end"
                subgraph_depth -= 1
            elif re.fullmatch(edge, line):
                continue
            else:
                assert re.fullmatch(node, line), (
                    f"{source_path}: unsupported flowchart statement {line!r}"
                )
        assert subgraph_depth == 0, f"{source_path}: unclosed flowchart subgraph"
        return

    if diagram_type == "sequenceDiagram":
        participants: set[str] = set()
        control_stack: list[str] = []
        for line in body:
            declaration = re.fullmatch(
                r"(?:actor|participant)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+as\s+.+)?",
                line,
            )
            if declaration:
                participants.add(declaration.group(1))
                continue
            control = re.match(r"(alt|opt|loop|par|critical|break|rect)\s+.+", line)
            if control:
                control_stack.append(control.group(1))
                continue
            if line.startswith("else "):
                assert control_stack and control_stack[-1] == "alt", (
                    f"{source_path}: else outside alt"
                )
                continue
            if line == "end":
                assert control_stack, f"{source_path}: unmatched sequence end"
                control_stack.pop()
                continue
            message = re.fullmatch(
                r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:->>|-->>)\s*"
                r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*.+",
                line,
            )
            assert message, f"{source_path}: unsupported sequence statement {line!r}"
            sender, receiver = message.groups()
            assert sender in participants, f"{source_path}: undeclared participant {sender}"
            assert receiver in participants, f"{source_path}: undeclared participant {receiver}"
        assert not control_stack, f"{source_path}: unclosed sequence control block"
        return

    if diagram_type == "stateDiagram-v2":
        transition = re.compile(
            r"(?:\[\*\]|[A-Za-z_][A-Za-z0-9_]*)\s+-->\s+"
            r"(?:\[\*\]|[A-Za-z_][A-Za-z0-9_]*)(?::\s+.+)?"
        )
        for line in body:
            assert re.fullmatch(transition, line), (
                f"{source_path}: unsupported state statement {line!r}"
            )
        return

    if diagram_type == "erDiagram":
        in_entity = False
        for line in body:
            if re.fullmatch(r"[A-Z][A-Z0-9_]* \{", line):
                assert not in_entity, f"{source_path}: nested ER entity"
                in_entity = True
            elif line == "}":
                assert in_entity, f"{source_path}: unmatched ER entity close"
                in_entity = False
            elif in_entity:
                assert re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+"
                    r"[A-Za-z_][A-Za-z0-9_]*(?:\s+.+)?",
                    line,
                ), f"{source_path}: invalid ER attribute {line!r}"
            else:
                assert re.fullmatch(
                    r"[A-Z][A-Z0-9_]*\s+[|o{}]+--[|o{}]+\s+"
                    r"[A-Z][A-Z0-9_]*\s*:\s*.+",
                    line,
                ), f"{source_path}: invalid ER relationship {line!r}"
        assert not in_entity, f"{source_path}: unclosed ER entity"
        return

    raise AssertionError(f"{source_path}: unsupported Mermaid type {diagram_type!r}")


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
        "[Release guide](RELEASE_GUIDE.md)",
        "[References](REFERENCES.md)",
    ):
        assert index_text.count(link) == 1
    assert "[docs/README.md](docs/README.md)" in read_text("README.md")


def test_release_guide_binds_source_artifact_migration_and_operations() -> None:
    """Require an executable release handoff without claiming branch evidence shipped."""

    release_text = read_text("docs/RELEASE_GUIDE.md")
    for heading in (
        "## Authority and release identity",
        "## Admission checklist",
        "## Build and provenance procedure",
        "## Migration and rollback procedure",
        "## Publication and deployment procedure",
        "## Protected-main operational acceptance",
        "## Abort and recovery conditions",
    ):
        assert heading in release_text
    for required_term in (
        "protected `main`",
        "exact source commit",
        "CycloneDX SBOM",
        "provenance",
        "reproducible",
        "independent non-author approval",
        "expand/backfill/contract",
        "rollback",
        "artifact digest",
        "protected-main",
        "does not claim",
    ):
        assert required_term in release_text


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


def test_mermaid_blocks_parse_supported_syntax_and_cover_required_views() -> None:
    """Parse the supported Mermaid subset and require all architecture views."""

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
        for block in blocks:
            validate_mermaid_subset(block, path)
        all_diagrams.extend(blocks)
    assert any(block.lstrip().startswith("stateDiagram-v2") for block in all_diagrams)

    invalid_sequence = """sequenceDiagram
        actor Caller
        Caller->>Undeclared: request
    """
    try:
        validate_mermaid_subset(invalid_sequence, "negative fixture")
    except AssertionError:
        pass
    else:  # pragma: no cover - proves the validator is fail-closed
        raise AssertionError("Mermaid validator accepted an undeclared participant")


def test_live_names_routes_and_physical_data_objects_are_not_stale() -> None:
    """Tie architecture names and ERD claims to protected-main source strings."""

    durable_text = canonical_text()
    assert "TaskOrchestrator" in durable_text
    assert "CostRoutingCoordinator" in durable_text
    assert "contextual_orchestrator.orchestrator.Agent" not in durable_text
    assert "contextual_orchestrator.orchestrator.Orchestrator" not in durable_text
    assert "Orchestrator.route_once" not in durable_text

    uml_text = read_text("docs/UML.md")
    coordinator_methods = class_method_names(
        "contextual_orchestrator/cost_router.py", "CostRoutingCoordinator"
    )
    for method_name in ("complete", "poll_batch", "retrieve_batch"):
        assert method_name in coordinator_methods
        assert f"{method_name}(...)" in uml_text
    assert "route_request(...)" not in uml_text
    assert "Server->>Router: poll_batch(...) or retrieve_batch(...)" in uml_text
    assert "Router->>Backend: poll(...) or retrieve(...)" in uml_text

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

    architecture_text = " ".join(read_text("ARCHITECTURE.md").lower().split())
    threat_text = " ".join(read_text("docs/THREAT_MODEL.md").lower().split())
    readme_text = " ".join(read_text("README.md").lower().split())
    assert "no dedicated trace scope" in architecture_text
    assert "inference-scoped caller may request" in architecture_text
    assert "no enforced provider-response byte cap" in threat_text
    assert "default in-memory credential backend is process-local" in readme_text
    assert "route-stream workflow runs remain memory-only" in readme_text
    assert "budget precheck is process-local and non-atomic" in readme_text
    assert "ordinary non-stream orchestrated calls" in readme_text

    sync_batch_adr = " ".join(
        read_text("docs/adr/0005-sync-batch-pg-llm-batch.md").lower().split()
    )
    assert "ordinary coordinator sync" in sync_batch_adr
    assert "passthrough and route streaming bypass" in sync_batch_adr
    route_conduct_adr = " ".join(
        read_text("docs/adr/0001-route-conduct-test-time-compute.md").lower().split()
    )
    assert "snapshotted policy" in route_conduct_adr
    assert "a versioned policy" not in route_conduct_adr


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


def test_dated_open_pr_snapshot_matches_the_audited_inventory() -> None:
    """Keep the sole volatile evidence ledger aligned with its dated audit."""

    traceability = read_text("docs/TRACEABILITY.md")
    assert "**Audit date:** 2026-08-11 (Asia/Seoul)" in traceability
    snapshot = traceability.split("## Dated open-PR snapshot", 1)[1].split(
        "## Dependency order from live refs", 1
    )[0]
    normalized_snapshot = " ".join(snapshot.split())
    assert "Audited contributor head (pre-write)" in snapshot
    assert "publishing this ledger necessarily advances" in normalized_snapshot
    assert "not post-write current-head claims" in normalized_snapshot
    observed = {
        int(number)
        for number in re.findall(r"^\| #(\d+) \|", snapshot, flags=re.MULTILINE)
    }
    assert observed == AUDITED_OPEN_PR_NUMBERS
    assert "#80" not in snapshot
    assert "#88" not in snapshot
    for audited_head in (
        "28088b9fc86d975b43637b7758d25e20d61c5786",  # PR #107
        "f5b9acc7256fd3e33d015b7ad020d4908aba38f6",  # PR #105
        "0fc208eb185e1306dbaad065a516a3e4cd2dbee4",  # PR #104
        "2502915a8e90059074167e6306b47148a1d40fdc",  # PR #99
        "73ed3a077f88a2f03cf734f1067bee2dcce2467f",  # PR #94
    ):
        assert audited_head in snapshot


def test_canonical_documentation_change_is_recorded_in_changelog() -> None:
    """Keep the buyer-visible canonical documentation graph in release history."""

    changelog = read_text("CHANGELOG.md")
    assert (
        "Establish a canonical status-qualified product documentation graph"
        in changelog
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run with pytest so every documentation contract executes.")
