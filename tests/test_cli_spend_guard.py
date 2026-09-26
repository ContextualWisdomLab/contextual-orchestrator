"""CLI on-ramp for the per-run spend guard and tenant metering (ADR 0138)."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from contextual_orchestrator.__main__ import main
from contextual_orchestrator.orchestrator import TaskOrchestrator


def test_cli_wires_guard_tenant_ledger_and_summary(tmp_path: Path) -> None:
    """Spend flags reach the orchestrator's guard and the run artifact is written."""
    summary_path = tmp_path / "artifacts" / "run-usage.json"
    ledger_path = tmp_path / "spend.jsonl"
    stdout = StringIO()
    with (
        patch.object(sys, "stdout", stdout),
        patch(
            "contextual_orchestrator.__main__.TaskOrchestrator", side_effect=TaskOrchestrator
        ) as orchestrator_cls,
    ):
        main([
            "--run-max-cost-usd", "1.5",
            "--tenant-id", "ContextualWisdomLab/example",
            "--spend-ledger-path", str(ledger_path),
            "--run-usage-summary", str(summary_path),
            "hello",
        ])
    guard = orchestrator_cls.call_args.kwargs["spend_guard"]
    assert guard.config.run_max_cost.as_float() == 1.5
    summary = json.loads(summary_path.read_text())
    assert summary["tenant_id"] == "ContextualWisdomLab/example"
    assert summary["budget"]["run_max_cost"] == 1.5
    assert summary["calls"]
    assert ledger_path.exists()
    assert json.loads(stdout.getvalue())["answer"]


def test_cli_rejects_missing_virtual_key_credential() -> None:
    """A named but unconfigured KV credential is an operator error, not a silent default."""
    with pytest.raises(SystemExit):
        main(["--virtual-key-credential", "SPEND_GUARD_TEST_ABSENT_VIRTUAL_KEY", "hello"])


def test_cli_rejects_removed_heuristic_baseline_ratio_option() -> None:
    """No caller-supplied numeric threshold can control baseline admission."""
    with pytest.raises(SystemExit):
        main(["--baseline-min-remaining-ratio", "0.25", "hello"])
