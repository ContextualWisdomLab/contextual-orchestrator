"""Issue #117 canonical status remains aligned with protected-main behavior."""

from pathlib import Path


def test_issue117_docs_do_not_reopen_integrated_security_slices() -> None:
    """Batch ownership and production migration stay recorded as implemented."""
    baseline = Path("docs/product-technical-gap-baseline.md").read_text()
    adr = Path("docs/planning/adrs/0026-trace-purpose-authorization.md").read_text()

    assert "owner-bound batch/workflow/evaluation reads" in baseline
    assert "production gate against legacy single-token mode" in baseline
    assert "remains open only for richer tenant/workspace/resource/lifetime" in adr
    assert "Protected\nmain already owner-binds batch jobs" in adr
    assert "batch jobs need their protected-main integration" not in adr
