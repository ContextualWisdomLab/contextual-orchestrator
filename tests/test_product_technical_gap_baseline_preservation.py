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
