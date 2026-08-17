"""Contracts for expanded ADRs and verified paper/standard citations."""

from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT_DIR / "docs" / "adr"
README_PATH = ROOT_DIR / "README.md"
REFERENCES_PATH = ROOT_DIR / "docs" / "REFERENCES.md"

REQUIRED_ADRS = (
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
)

TRINITY_MARKERS = (
    "Xu, J.",
    "arXiv:2512.04695",
    "https://doi.org/10.48550/arXiv.2512.04695",
)
CONDUCTOR_MARKERS = (
    "Nielsen, S.",
    "arXiv:2512.04388",
    "https://doi.org/10.48550/arXiv.2512.04388",
)
FUGU_MARKERS = (
    "Tang, Y.",
    "arXiv:2606.21228",
    "https://doi.org/10.48550/arXiv.2606.21228",
)

FORBIDDEN_AUTHOR_LINES = (
    "Zhang, L.",
    "Zhang et al.",
    "Li, Z.",
    "Li et al.",
    "Zhang/Li",
)


def read_text(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_adr_index_and_files_exist() -> None:
    index = read_text("docs/adr/README.md")
    assert "Architecture Decision Records" in index
    assert "Xu et al." in index
    assert "Nielsen et al." in index
    assert "composition hubs" in index
    for name in REQUIRED_ADRS:
        path = ADR_DIR / name
        assert path.is_file(), f"missing ADR {name}"
        assert name.split("-")[0] in index


def test_references_use_apa7_doi_or_url() -> None:
    text = read_text("docs/REFERENCES.md")
    for marker in TRINITY_MARKERS + CONDUCTOR_MARKERS + FUGU_MARKERS:
        assert marker in text
    assert "https://doi.org/10.17487/RFC9110" in text
    assert "https://doi.org/10.6028/NIST.AI.600-1" in text
    assert "https://www.iso.org/standard/81230.html" in text
    assert "to appear" in text
    collapsed = " ".join(text.split())
    assert "not treated as a final" in collapsed or "not cited as the proceedings" in collapsed


def test_trinity_and_conductor_authors_are_xu_and_nielsen() -> None:
    corpus = "\n".join(
        [
            read_text("docs/REFERENCES.md"),
            read_text("docs/adr/0001-route-conduct-test-time-compute.md"),
            read_text("docs/adr/0003-workflow-access-and-reasoning-control.md"),
            read_text("docs/architecture.md"),
        ]
    )
    assert "Xu, J." in corpus
    assert "Nielsen, S." in corpus
    assert "Jinglue Xu" in read_text("docs/REFERENCES.md") or "Xu, J." in corpus
    for forbidden in FORBIDDEN_AUTHOR_LINES:
        assert forbidden not in corpus


def test_paper_adrs_expand_verified_claims() -> None:
    route = read_text("docs/adr/0001-route-conduct-test-time-compute.md")
    access = read_text("docs/adr/0003-workflow-access-and-reasoning-control.md")
    for text in (route, access):
        assert "Xu, J." in text
        assert "Nielsen, S." in text
        assert "https://doi.org/10.48550/arXiv.2512.04695" in text
        assert "https://doi.org/10.48550/arXiv.2512.04388" in text
        assert "Preprint" in text
        assert "not" in text.lower() and "proceedings" in text.lower()
        assert len(text) > 2500


def test_composition_hubs_are_not_msa_violations() -> None:
    boundary = read_text("docs/adr/0012-standalone-and-cwl-boundary.md")
    assert "naruon" in boundary
    assert "gyeot" in boundary
    assert "composition hubs" in boundary
    assert "not an MSA violation" in boundary
    assert "Do not rip sibling links" in boundary
    assert "https://github.com/ContextualWisdomLab/naruon" in boundary
    assert "https://github.com/ContextualWisdomLab/gyeot" in boundary
    assert "https://github.com/ContextualWisdomLab/clearfolio" in boundary
    assert "https://github.com/ContextualWisdomLab/pg-llm-batch" in boundary


def test_readme_stays_operator_facing() -> None:
    readme = read_text("README.md")
    lowered = readme.lower()
    assert "bot procedure" not in lowered
    assert "agent procedure" not in lowered
    assert "docs/adr/README.md" in readme
    assert "Naruon and gyeot may call this gateway" in readme


def test_architecture_and_planning_keep_verified_citations() -> None:
    architecture = read_text("docs/architecture.md")
    planning = read_text("docs/product_planning.md")
    papers = read_text("docs/papers/README.md")
    for text in (architecture, planning):
        assert "Xu, J." in text or "Xu et al." in text
        assert "Nielsen, S." in text or "Nielsen et al." in text
        assert "arXiv:2512.04695" in text
        assert "arXiv:2512.04388" in text
        assert "to appear" in text
    assert "https://doi.org/10.48550/arXiv.2305.05176" in papers
    assert "https://doi.org/10.48550/arXiv.2406.18665" in papers
    assert "https://doi.org/10.48550/arXiv.2404.14618" in papers


def test_standards_appear_in_security_adrs() -> None:
    kv = read_text("docs/adr/0004-kv-credential-bootstrap.md")
    privacy = read_text("docs/adr/0009-purpose-bound-pii-protection.md")
    egress = read_text("docs/adr/0015-provider-egress-response-trust.md")
    assert "NIST SP 800-218" in kv
    assert "ISO/IEC 27001:2022" in kv
    assert "NIST AI 600-1" in privacy
    assert "ISO/IEC 42001:2023" in privacy
    assert "RFC 9110" in egress
    assert "https://doi.org/10.17487/RFC9110" in egress


if __name__ == "__main__":  # pragma: no cover
    test_adr_index_and_files_exist()
    test_references_use_apa7_doi_or_url()
    test_trinity_and_conductor_authors_are_xu_and_nielsen()
    test_paper_adrs_expand_verified_claims()
    test_composition_hubs_are_not_msa_violations()
    test_readme_stays_operator_facing()
    test_architecture_and_planning_keep_verified_citations()
    test_standards_appear_in_security_adrs()
    print("ok")
