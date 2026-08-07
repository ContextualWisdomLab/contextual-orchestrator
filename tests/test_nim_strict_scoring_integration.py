"""End-to-end contracts for the supported strict NIM benchmark command."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys

from contextual_orchestrator.nim_csv_evidence import (
    run_benchmark_cli_with_complete_csv,
)
from contextual_orchestrator.nim_strict_scoring import (
    STRICT_SCORING_POLICY_VERSION,
    run_strict_benchmark_cli,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_ordinary_package_import_does_not_activate_optional_nim_modules() -> None:
    """Gateway consumers must not import or activate benchmark-only adapters."""
    script = """
import json
import sys

import contextual_orchestrator

print(json.dumps({
    "benchmark": "contextual_orchestrator.nim_benchmark" in sys.modules,
    "csv_evidence": "contextual_orchestrator.nim_csv_evidence" in sys.modules,
    "strict_scoring": "contextual_orchestrator.nim_strict_scoring" in sys.modules,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "benchmark": False,
        "csv_evidence": False,
        "strict_scoring": False,
    }


def test_supported_dry_run_publishes_only_strict_locked_scores(
    tmp_path: Path,
) -> None:
    """The real supported CLI must bind artifacts to strict scorer versions."""
    output_directory = tmp_path / "strict-artifacts"
    stdout = io.StringIO()

    result = run_benchmark_cli_with_complete_csv(
        [
            "--dry-run",
            "--output-dir",
            str(output_directory),
            "--max-total-requests",
            "2000",
        ],
        benchmark_cli=run_strict_benchmark_cli,
        stdout=stdout,
    )

    assert result == 0
    success = json.loads(stdout.getvalue())
    report_path = Path(success["artifact_paths"]["json_path"])
    csv_path = Path(success["artifact_paths"]["csv_path"])
    markdown_path = Path(success["artifact_paths"]["markdown_path"])
    assert report_path.parent == output_directory
    assert csv_path.parent == output_directory
    assert markdown_path.parent == output_directory

    report = json.loads(report_path.read_text(encoding="utf-8"))
    parameters = report["provenance"]["benchmark_parameters"]
    assert parameters["task_manifest_version"].endswith(
        "+strict." + STRICT_SCORING_POLICY_VERSION
    )
    assert report["provenance"]["task_manifest_sha256"]
    assert {
        (cell["scorer_name"], cell["scorer_version"])
        for cell in report["evaluation"]["evaluation_cells"]
    } == {
        ("exact_number_match", "2"),
        ("exact_text_match", "1"),
    }
    assert report["evaluation"]["routing_recommendation"] is None


def test_entrypoint_and_permanent_quality_gate_bind_strict_scoring() -> None:
    """Static contracts prevent the supported path from bypassing strict scoring."""
    entrypoint = (
        REPOSITORY_ROOT / "contextual_orchestrator" / "__main__.py"
    ).read_text(encoding="utf-8")
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"
    ).read_text(encoding="utf-8")

    assert "from .nim_strict_scoring import run_strict_benchmark_cli" in entrypoint
    assert "benchmark_cli=run_strict_benchmark_cli" in entrypoint
    assert "contextual_orchestrator.nim_strict_scoring" in workflow
    assert "tests/test_nim_strict_scorer_validity.py" in workflow
    assert "tests/test_nim_strict_scoring_integration.py" in workflow
    assert "interrogate -f 100 contextual_orchestrator/nim_strict_scoring.py" in workflow
