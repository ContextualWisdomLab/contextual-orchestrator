"""Contract tests for ADR 0127's no-heuristics timeout-measurement design."""

from pathlib import Path


ADR = Path("docs/planning/adrs/0127-evidence-based-per-model-timeout-allocator.md")


def test_timeout_design_has_no_fixed_sample_or_fallback_decision_rules() -> None:
    """Reject repository-authored sample floors, retention caps, and fallback pooling."""
    text = ADR.read_text(encoding="utf-8")
    forbidden = (
        "~20",
        "~60",
        "~120",
        "most recent 2,000",
        "borrowed aggregate",
        "coarser aggregate",
        "sample-size gated",
    )
    for token in forbidden:
        assert token not in text


def test_timeout_design_fails_closed_without_identified_statistical_decision_model() -> None:
    """Require explicit uncertainty math and null output when a timeout decision is unidentified."""
    text = ADR.read_text(encoding="utf-8")
    assert "Binomial" in text
    assert "Kaplan" in text and "Meier" in text
    assert "Brookmeyer" in text and "Crowley" in text
    assert "operator-supplied" in text
    assert "no automatic timeout recommendation" in text.lower()
    assert "fail closed" in text.lower()


if __name__ == "__main__":  # pragma: no cover
    test_timeout_design_has_no_fixed_sample_or_fallback_decision_rules()
    test_timeout_design_fails_closed_without_identified_statistical_decision_model()
    print("ok")
