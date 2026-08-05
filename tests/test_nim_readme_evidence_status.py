"""Contract tests for buyer-facing NIM benchmark evidence-status wording."""

from pathlib import Path


README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def test_nim_readme_describes_completion_dependent_evidence_status() -> None:
    """Explain both evidence outcomes without claiming automatic routing changes."""
    readme = README_PATH.read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    assert "The bundled manifest contains thirty locked tasks." in normalized
    assert (
        "It may reach `evidence_review_required` when at least 90% of policy-task "
        "cells complete and the paired-task floor is met; otherwise it reports "
        "`insufficient_evidence`." in normalized
    )
    assert (
        "no benchmark artifact automatically changes production routing"
        in normalized
    )
    assert (
        "manifest is smoke-sized and reports `insufficient_evidence`"
        not in normalized
    )
