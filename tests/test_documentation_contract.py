"""Machine-check the canonical product and architecture documentation graph."""

import ast
import re
from pathlib import Path

import pytest


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
    "docs/evidence/README.md",
    "docs/evidence/2026-08-11-documentation-audit.md",
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
    "docs/TRACEABILITY.md",
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
    "docs/evidence/README.md",
    "docs/evidence/2026-08-11-documentation-audit.md",
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
    108,
    109,
}


def read_text(relative_path: str) -> str:
    """Return one repository file as UTF-8 text."""

    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def canonical_text() -> str:
    """Return durable canonical documents without the dated evidence appendix."""

    return "\n".join(read_text(path) for path in CANONICAL_FILES)


DATED_EVIDENCE_APPENDIX = "docs/evidence/2026-08-11-documentation-audit.md"


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
        "[Dated evidence appendices](evidence/README.md)",
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


def test_active_local_mlx_work_is_status_qualified_across_canonical_docs() -> None:
    """Keep the active local-provider slice distinct from shipped behavior."""

    canonical_paths = (
        "ARCHITECTURE.md",
        "docs/PRD.md",
        "docs/TRD.md",
        "docs/TRACEABILITY.md",
    )
    for path in canonical_paths:
        matching_lines = [
            line
            for line in read_text(path).splitlines()
            if "PR #109" in line and "MLX" in line
        ]
        assert matching_lines, f"{path} must trace the PR #109 MLX slice"
        assert any("`active_pr`" in line for line in matching_lines), (
            f"{path} must label the PR #109 MLX slice active_pr"
        )

    trd_lines = [
        line
        for line in read_text("docs/TRD.md").splitlines()
        if "PR #109" in line and "MLX" in line
    ]
    assert any("FR-015" in line for line in trd_lines)


def test_root_readme_uses_current_buyer_facing_product_identity() -> None:
    """Keep the entry point aligned with the governed orchestration product."""

    readme = read_text("README.md")
    normalized_readme = " ".join(readme.split())
    assert (
        "Provider-neutral OpenAI-compatible orchestration control plane that "
        "routes, conducts, verifies, and synthesizes work across governed model "
        "agents."
        in normalized_readme
    )
    assert "Stdlib Python lab for a single API" not in readme
    assert "hardened for local deployment" in readme
    assert "hardened for local lab use" not in readme
    assert "stdlib lab" not in readme.lower()
    assert "standalone deployment" in readme.lower()
    assert "This is not a Sakana AI product" not in readme
    assert (
        "independently implemented from published orchestration concepts"
        in normalized_readme
    )
    assert (
        "no third-party trained model weights or proprietary artifacts"
        in normalized_readme
    )


def test_product_planning_qualifies_enterprise_identity_and_authorization() -> None:
    """Prevent supporting product plans from overstating the auth boundary."""

    planning = read_text("docs/product_planning.md").lower()

    assert "stdlib lab" not in planning
    assert "coarse admin and inference bearer scopes" in planning
    assert "no tenant-aware rbac" in planning
    assert "host owns enterprise identity and tenancy" in planning


def test_library_research_uses_current_stack_and_status_vocabulary() -> None:
    """Supporting library research must describe the live stack without lab names."""

    research = read_text("docs/library_research.md")

    for stale_term in ("current lab", "current stdlib prototype", "Ponytail"):
        assert stale_term not in research

    for required_term in (
        "implemented_on_protected_main",
        "accepted_architecture",
        "planned",
        "ThreadingHTTPServer",
        "handwritten OpenAPI",
        "static admin UI",
        "optional `api` extra",
        "does not dispatch through FastAPI",
        "optional `db` extra",
        "does not use SQLAlchemy ORM or Alembic migrations",
    ):
        assert required_term in research


def test_agent_and_cdd_guidance_use_current_product_and_adoption_language() -> None:
    """Keep agent and CDD guidance aligned with the current product authority."""

    claude = read_text("CLAUDE.md")
    workflow = read_text("conductor/workflow.md")
    stack = read_text("conductor/tech-stack.md")
    combined = "\n".join((claude, workflow, stack))
    normalized = " ".join(combined.split()).lower()

    for stale_term in (
        "stdlib-Python lab",
        "Ponytail design gate",
        "Ponytail Design Gate",
        "after this lab hardens",
    ):
        assert stale_term not in combined

    for required_term in (
        "provider-neutral OpenAI-compatible orchestration control plane",
        "dependency-adoption gate",
        "current implementation dependencies",
        "planned adoption candidates",
        "optional extras are installable compatibility surfaces",
    ):
        assert required_term.lower() in normalized


def test_supporting_runtime_docs_use_status_qualified_product_language() -> None:
    """Keep supporting runtime guides explicit about shipped and planned scope."""

    analytics = read_text("docs/analytics_spec.md")
    api_design = read_text("docs/rest_api_design.md")
    i18n = read_text("docs/i18n_design.md")
    combined = "\n".join((analytics, api_design, i18n))
    normalized = " ".join(combined.split()).lower()

    for stale_term in (
        "prototype",
        "Production Library Target",
        "dependency-free",
    ):
        assert stale_term not in combined

    assert combined.count("**Document state:**") == 3
    for required_term in (
        "implemented_on_protected_main",
        "standalone runtime",
        "not production telemetry",
        "planned adoption candidate",
        "optional compatibility extras",
    ):
        assert required_term.lower() in normalized


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
    assert sha_pattern.search(read_text(DATED_EVIDENCE_APPENDIX)) is not None


def test_dated_open_pr_snapshot_matches_the_audited_inventory() -> None:
    """Keep the sole volatile evidence ledger aligned with its dated audit."""

    evidence = read_text(DATED_EVIDENCE_APPENDIX)
    assert "**Audit date:** 2026-08-11 (Asia/Seoul)" in evidence
    snapshot = evidence.split("## Dated open-PR snapshot", 1)[1].split(
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
        "ada372df205271c74ad095e898644588c7156075",  # PR #109
        "8760993cb8262922a771948845c8dfd2afefb773",  # PR #108
        "28088b9fc86d975b43637b7758d25e20d61c5786",  # PR #107
        "828ca54f2b96a3bdd7adec24a26c0d8164df47d1",  # PR #105
        "8453f082672d96b564ff2c32d028b11e05d8729f",  # PR #104
        "2502915a8e90059074167e6306b47148a1d40fdc",  # PR #99
        "73ed3a077f88a2f03cf734f1067bee2dcce2467f",  # PR #94
    ):
        assert audited_head in snapshot


def test_dated_central_prerequisite_snapshot_is_fail_closed() -> None:
    """Keep incomplete central dependencies distinct from accepted authority."""

    evidence = read_text(DATED_EVIDENCE_APPENDIX)
    assert '.github PR #929 JSON repair: test-only RED' in evidence
    assert '.github issue #907 wrapper repair: no completing PR' in evidence
    assert "#906 had ten green" in evidence
    assert "no formal review or qualifying approval" in evidence
    assert "no production repair or associated workflow run" in evidence
    assert "None of those states is protected integration" in evidence


def test_canonical_documentation_change_is_recorded_in_changelog() -> None:
    """Keep the buyer-visible canonical documentation graph in release history."""

    changelog = read_text("CHANGELOG.md")
    assert (
        "Establish a canonical status-qualified product documentation graph"
        in changelog
    )
    assert "Add a canonical release, migration, and rollback guide" in changelog
    assert "Replace legacy lab framing in the root README" in changelog
    assert "Replace the competitor-centric README disclaimer" in changelog
    assert "Remove the remaining stdlib-lab qualifier" in changelog
    assert "Replace stale lab/prototype and internal-name language" in changelog
    assert "Align Claude and conductor guidance" in changelog
    assert "Status-qualify the analytics, REST API" in changelog


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run with pytest so every documentation contract executes.")


def test_usage_evidence_adrs_define_one_mode_complete_contract() -> None:
    """Keep every execution mode on one qualified usage-evidence contract."""

    routing_adr = " ".join(
        read_text("docs/adr/0005-sync-batch-pg-llm-batch.md").lower().split()
    )
    evidence_adr = " ".join(
        read_text("docs/adr/0006-honest-cost-and-benchmark-evidence.md").lower().split()
    )
    for mode in ("sync completion", "batch retrieval", "passthrough", "route streaming"):
        assert mode in routing_adr
    for status in ("unknown", "not_recorded"):
        assert chr(96) + status + chr(96) in routing_adr
    assert "excluded from cost comparison" in routing_adr

    for dimension in (
        "account",
        "service",
        "upstream_api",
        "model_name",
        "team",
        "group",
        "company",
    ):
        assert chr(96) + dimension + chr(96) in evidence_adr
    assert "mode-by-mode completeness tests" in evidence_adr
    assert "writer and export path" in evidence_adr


def test_access_grant_model_is_directional_and_predecessor_bounded() -> None:
    """Require consumer-to-producer access without bidirectional visibility."""

    erd = " ".join(read_text("docs/ERD.md").split())
    for term in (
        "ACCESS_GRANT {",
        "consumer_step_id",
        "producer_step_id",
        "authorized producer",
        "earlier workflow step",
        "does not grant bidirectional visibility",
    ):
        assert term in erd
    assert "WORKFLOW_STEP }o--o{ WORKFLOW_STEP : exposes_by_access_list" not in erd


def test_planned_web_dependencies_are_not_presented_as_package_extras() -> None:
    """Keep unshipped web-client frameworks explicitly planned."""

    i18n = read_text("docs/i18n_design.md")
    assert "i18next and React-admin are planned adoption candidates" in i18n
    assert "i18next and React-admin are optional compatibility extras" not in i18n


def test_hybrid_llm_source_and_license_authority_are_linked() -> None:
    """Link paper provenance separately from arXiv license evidence."""

    paper_index = read_text("docs/papers/README.md")
    references = read_text("docs/REFERENCES.md")
    license_authority = "https://arxiv.org/abs/2404.14618"
    assert license_authority in paper_index
    assert license_authority in references
    assert "https://openreview.net/forum?id=02f3mUtqnM" in paper_index
    assert "https://openreview.net/forum?id=02f3mUtqnM" in references


def test_prd_and_trd_require_all_coverage_dimensions() -> None:
    """Align product and technical release gates with ADR-0016."""

    required_contract = "statement, branch, function, and line coverage"
    for path in (
        "docs/PRD.md",
        "docs/TRD.md",
        "docs/adr/0016-complete-coverage-docstrings.md",
    ):
        assert required_contract in " ".join(read_text(path).split())


def test_canonical_authority_state_cells_use_only_status_vocabulary() -> None:
    """Reject descriptive prose in the canonical authority state column."""

    index_text = read_text("docs/README.md")
    rows = [
        line
        for line in index_text.splitlines()
        if line.startswith("| ") and not line.startswith("|---")
    ]
    authority_rows = [line for line in rows if "[" in line and "](" in line]
    assert authority_rows
    for row in authority_rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 5
        state = cells[3].strip(chr(96))
        assert state in STATUS_VOCABULARY, row


def test_provider_failure_uml_separates_caller_and_provider_failures() -> None:
    """Keep caller rejection terminal while documenting eligible provider failover."""

    uml = read_text("docs/UML.md")
    for line in (
        "alt caller validation error",
        "Orchestrator-->>Orchestrator: Terminate without provider dispatch",
        "alt transient provider failure",
        "else permanent provider or configuration error",
        "Orchestrator->>Fallback: Invoke eligible candidate without client retry",
    ):
        assert line in uml


def test_deployment_uml_keeps_credentials_behind_provider_adapter() -> None:
    """Keep credential retrieval out of the orchestration-policy boundary."""

    uml = read_text("docs/UML.md")
    assert 'provider_adapter["Provider adapter"]' in uml
    assert "policy --> provider_adapter" in uml
    assert "provider_adapter --> kv" in uml
    assert "policy --> kv" not in uml


def _assert_independent_review_evidence_fails_closed(decision: str) -> None:
    """Assert that ADR-0010 retains every fail-closed review control."""

    normalized = " ".join(decision.split())
    required_controls = (
        "`reviewDecision` must be `APPROVED` for the unchanged head",
        (
            "A missing decision, `REVIEW_REQUIRED`, or `CHANGES_REQUESTED` "
            "blocks the mutation even when branch protection currently allows "
            "zero approvals"
        ),
        "An eligible independent non-author approval must also be present",
        (
            "the aggregate field is evidence of the combined repository state, "
            "not a substitute reviewer"
        ),
        (
            "A completed, successful, structured same-head Strix report is "
            "separately required"
        ),
        (
            "Queued, in-progress, neutral/no-report, cancelled, skipped, absent, "
            "or predecessor-head Strix states block merge"
        ),
        (
            "If the aggregate review state regresses or a required check becomes "
            "incomplete after auto-merge is queued, automation disables that "
            "queued mutation and starts exact-head verification again"
        ),
    )
    for required_control in required_controls:
        assert required_control in normalized


def test_independent_review_evidence_fails_closed() -> None:
    """Require canonical review evidence to reject incomplete aggregate gates."""

    decision = read_text("docs/adr/0010-independent-review-and-evidence.md")
    _assert_independent_review_evidence_fails_closed(decision)

    semantic_regressions = (
        (
            "blocks the mutation even when branch protection currently allows "
            "zero approvals",
            "is advisory when branch protection currently allows zero approvals",
        ),
        (
            "An eligible independent non-author approval must also be present",
            "An eligible independent non-author approval is optional",
        ),
        (
            "structured same-head Strix report is separately required",
            "structured same-head Strix report is advisory",
        ),
        (
            "block merge",
            "may permit merge",
        ),
        (
            "automation disables that queued mutation",
            "automation retains that queued mutation",
        ),
    )
    normalized = " ".join(decision.split())
    for required_control, weakened_control in semantic_regressions:
        assert required_control in normalized
        weakened = normalized.replace(required_control, weakened_control, 1)
        with pytest.raises(AssertionError):
            _assert_independent_review_evidence_fails_closed(weakened)

def test_canonical_documentation_has_no_trailing_whitespace() -> None:
    """Keep canonical Markdown compatible with diff-integrity gates."""

    for path in REQUIRED_FILES:
        document = read_text(path)
        assert not document.endswith("\n\n"), f"{path}: final blank line"
        for line_number, line in enumerate(document.splitlines(), start=1):
            assert line == line.rstrip(), f"{path}:{line_number}"
