"""Protect the canonical Gap baseline from accidental partial-file replacement."""

from pathlib import Path


BASELINE_PATH = Path(__file__).parents[1] / "docs" / "product-technical-gap-baseline.md"
PROTECTED_AUTHORITY_SECTIONS = (
    "## 1. Executive Summary",
    "## 2. Product Requirements Document (PRD) Gaps",
    "## 3. Technical Requirements Document (TRD) Gaps",
    "## 4. Ecosystem Integration Gaps",
    "## 5. Action Plan & Roadmap (Loop Strategy)",
    "## 2026-09-09 Decision-latency durable acknowledgement gap",
    "## 2026-08-30 full incident timeline: the verdict-checker isn't the bug, here's what actually collided",
    "## 3. Current architecture and UML-level flow",
    "## 6. Prioritized gap register",
    "## 7. Delivery gates",
)


def test_product_technical_gap_baseline_preserves_protected_authority_sections() -> None:
    """Require representative protected PRD, TRD, roadmap, architecture, and incident authority."""

    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    missing = [
        section for section in PROTECTED_AUTHORITY_SECTIONS if section not in baseline
    ]

    assert missing == [], (
        "docs/product-technical-gap-baseline.md dropped protected authority sections: "
        + ", ".join(missing)
    )

def test_multimodal_owner_evidence_preserves_verified_repair_lineage() -> None:
    """Keep judge failover and role-aware preflight repairs reconstructable."""

    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    required_revisions = (
        "7f69bacb0d35f00e6902df8e440efeafbe08dbe3",
        "37435b5e82e9fe53abc67b032c67df83425c0250",
        "2b5c290ca56526c26f390949aecd87d85c2462b6",
        "b7440092d1cda47008271ed658fe372f536dd58f",
    )

    assert all(revision in baseline for revision in required_revisions)

