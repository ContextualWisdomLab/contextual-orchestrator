"""Keep public MCP advisory contracts aligned with bounded version evaluation."""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _assert_bounded_claim_contract(text: str) -> None:
    """Check the declared bounded contract, including wrapped stale denials."""
    paragraph = " ".join(text.split())
    assert "exact SemVer" in paragraph
    assert "npm" in paragraph and "crates.io" in paragraph
    assert "finding_allowed" in paragraph
    assert "GHSA" in paragraph and "unverified" in paragraph
    assert "versions_checked=false" in paragraph.replace("`", "")
    assert "never `rejected`" in paragraph or "never rejected" in paragraph
    for denial in (
        "versions/ranges are not checked",
        "affected ranges are not checked",
        "a match stays `unverified` because",
        "installed versions are vulnerable is a separate, unbuilt",
    ):
        assert denial not in paragraph


@pytest.mark.parametrize("document,start,end", [
    ("docs/kv-credentials.md", "`assess_vulnerability_claim` takes", "### Agent credential naming"),
    ("docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md",
     "The bounded server role", "### 3. A2A Gateway"),
    ("docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md",
     "- **grounding**", "- **engine**"),
])
def test_public_claim_contract_matches_version_authority(document, start, end):
    """Read the complete named contract instead of only its first physical line."""
    text = (ROOT / document).read_text(encoding="utf-8")
    assert text.count(start) == 1
    section = text.split(start, 1)[1].split(end, 1)[0]
    assert end in text.split(start, 1)[1]
    _assert_bounded_claim_contract(section)


@pytest.mark.parametrize("denial", [
    "versions/ranges are not\nchecked",
    "affected ranges are\nnot checked",
    "a match stays `unverified`\nbecause ranges are unsupported",
    "whether installed versions are vulnerable is a separate,\nunbuilt concern",
])
def test_contract_guard_rejects_wrapped_contradictions(denial):
    """A supported clause cannot hide a later contradictory wrapped statement."""
    supported = ("Bounded CVE exact SemVer npm/crates.io evidence may authorize "
                 "finding_allowed=true, including with versions_checked=false when "
                 "other lock copies were not evaluated; such an unaffected subset "
                 "is never rejected. GHSA ranges remain unverified.")
    _assert_bounded_claim_contract(supported.replace("exact SemVer", "exact\nSemVer"))
    with pytest.raises(AssertionError):
        _assert_bounded_claim_contract(supported + "\n" + denial)


def test_contract_guard_requires_partial_evaluation_disclosure():
    """A contract omitting supported-with-unchecked-copies is incomplete."""
    with pytest.raises(AssertionError):
        _assert_bounded_claim_contract(
            "Bounded CVE exact SemVer npm/crates.io evidence may authorize "
            "finding_allowed=true. GHSA ranges and incomplete evidence remain unverified."
        )
