"""Regression tests for transactional NIM benchmark artifact publication."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from contextual_orchestrator import nim_csv_evidence as csv_evidence

_ARTIFACT_NAMES = (
    "benchmark_report.json",
    "benchmark_cells.csv",
    "benchmark_summary.md",
)


def _model_use() -> dict[str, str]:
    """Return one valid deterministic model-assignment record."""
    return {
        "step_id": "step_one",
        "role": "worker",
        "agent_id": "agent_one",
        "model_id": "vendor/model-one",
    }


def _write_complete_artifacts(output_directory: Path, *, valid_report: bool = True) -> None:
    """Write one complete benchmark artifact set for wrapper-level tests."""
    output_directory.mkdir(parents=True, exist_ok=False)
    report: object
    if valid_report:
        report = {
            "evaluation": {
                "evaluation_cells": [
                    {
                        "policy_name": "route_once",
                        "task_id": "task_one",
                        "models_used": [_model_use()],
                    }
                ]
            }
        }
    else:
        report = {"evaluation": {"evaluation_cells": "invalid"}}
    (output_directory / "benchmark_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    (output_directory / "benchmark_cells.csv").write_text(
        "policy_name,task_id,task_score\r\nroute_once,task_one,1.0\r\n",
        encoding="utf-8",
    )
    (output_directory / "benchmark_summary.md").write_text(
        "# staged benchmark summary\n",
        encoding="utf-8",
    )


def _successful_benchmark_cli(argv: list[str]) -> int:
    """Write valid artifacts to the output directory supplied by the wrapper."""
    output_directory = csv_evidence.output_directory_from_argv(argv)
    _write_complete_artifacts(output_directory)
    print(
        json.dumps(
            {
                "run_mode": "dry_run",
                "artifact_paths": {
                    "json_path": str(output_directory / "benchmark_report.json"),
                    "csv_path": str(output_directory / "benchmark_cells.csv"),
                    "markdown_path": str(output_directory / "benchmark_summary.md"),
                },
            }
        )
    )
    return 0


def _publication_residue(parent: Path, final_name: str) -> list[Path]:
    """Return staging or backup directories left beside a final artifact set."""
    return sorted(
        [
            *parent.glob(f".{final_name}.staging-*"),
            *parent.glob(f".{final_name}.backup-*"),
        ]
    )


def test_success_publishes_one_complete_set_and_returns_final_paths(
    tmp_path: Path,
) -> None:
    """A successful run exposes only the enriched final artifact directory."""
    final_directory = tmp_path / "buyer_evidence"
    stdout = io.StringIO()

    result = csv_evidence.run_benchmark_cli_with_complete_csv(
        ["--dry-run", "--output-dir", str(final_directory)],
        benchmark_cli=_successful_benchmark_cli,
        stdout=stdout,
    )

    assert result == 0
    assert sorted(path.name for path in final_directory.iterdir()) == sorted(
        _ARTIFACT_NAMES
    )
    csv_text = (final_directory / "benchmark_cells.csv").read_text(encoding="utf-8")
    assert "models_used_json" in csv_text
    payload = json.loads(stdout.getvalue())
    assert payload["artifact_paths"] == {
        "json_path": str(final_directory / "benchmark_report.json"),
        "csv_path": str(final_directory / "benchmark_cells.csv"),
        "markdown_path": str(final_directory / "benchmark_summary.md"),
    }
    assert _publication_residue(tmp_path, final_directory.name) == []


def test_fresh_target_failure_leaves_no_visible_or_hidden_partial_set(
    tmp_path: Path,
) -> None:
    """CSV enrichment failure must not expose a new partial artifact set."""
    final_directory = tmp_path / "buyer_evidence"

    def invalid_success(argv: list[str]) -> int:
        staged_directory = csv_evidence.output_directory_from_argv(argv)
        _write_complete_artifacts(staged_directory, valid_report=False)
        print(json.dumps({"run_mode": "dry_run", "artifact_paths": {}}))
        return 0

    stdout = io.StringIO()
    result = csv_evidence.run_benchmark_cli_with_complete_csv(
        ["--output-dir", str(final_directory)],
        benchmark_cli=invalid_success,
        stdout=stdout,
    )

    assert result == 1
    assert json.loads(stdout.getvalue())["benchmark_failed_closed"] is True
    assert not final_directory.exists()
    assert _publication_residue(tmp_path, final_directory.name) == []


def test_failure_preserves_an_existing_complete_artifact_set(tmp_path: Path) -> None:
    """Pre-publication failure must leave a prior complete set byte-identical."""
    final_directory = tmp_path / "buyer_evidence"
    final_directory.mkdir()
    original_bytes: dict[str, bytes] = {}
    for artifact_name in _ARTIFACT_NAMES:
        artifact_path = final_directory / artifact_name
        artifact_path.write_bytes(f"prior:{artifact_name}\n".encode())
        original_bytes[artifact_name] = artifact_path.read_bytes()

    def invalid_success(argv: list[str]) -> int:
        staged_directory = csv_evidence.output_directory_from_argv(argv)
        _write_complete_artifacts(staged_directory, valid_report=False)
        print(json.dumps({"run_mode": "dry_run", "artifact_paths": {}}))
        return 0

    result = csv_evidence.run_benchmark_cli_with_complete_csv(
        ["--output-dir", str(final_directory)],
        benchmark_cli=invalid_success,
        stdout=io.StringIO(),
    )

    assert result == 1
    assert {
        artifact_name: (final_directory / artifact_name).read_bytes()
        for artifact_name in _ARTIFACT_NAMES
    } == original_bytes
    assert _publication_residue(tmp_path, final_directory.name) == []


def test_mid_publication_failure_rolls_back_the_prior_complete_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure after backup creation restores the exact prior directory."""
    final_directory = tmp_path / "buyer_evidence"
    final_directory.mkdir()
    for artifact_name in _ARTIFACT_NAMES:
        (final_directory / artifact_name).write_text(
            f"prior:{artifact_name}\n",
            encoding="utf-8",
        )
    original = {
        path.name: path.read_bytes()
        for path in final_directory.iterdir()
    }
    real_replace = os.replace
    failed_once = False

    def fail_staging_publish(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        nonlocal failed_once
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            not failed_once
            and source_path.name.startswith(f".{final_directory.name}.staging-")
            and destination_path == final_directory
        ):
            failed_once = True
            raise OSError("simulated directory publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(csv_evidence.os, "replace", fail_staging_publish)
    stdout = io.StringIO()
    result = csv_evidence.run_benchmark_cli_with_complete_csv(
        ["--output-dir", str(final_directory)],
        benchmark_cli=_successful_benchmark_cli,
        stdout=stdout,
    )

    assert failed_once is True
    assert result == 1
    assert json.loads(stdout.getvalue())["error_class"] == "OSError"
    assert {
        path.name: path.read_bytes()
        for path in final_directory.iterdir()
    } == original
    assert _publication_residue(tmp_path, final_directory.name) == []


def test_interrupted_backup_is_recovered_before_the_next_run(tmp_path: Path) -> None:
    """A sole crash backup is restored when the final directory is absent."""
    final_directory = tmp_path / "buyer_evidence"
    backup_directory = tmp_path / f".{final_directory.name}.backup-interrupted"
    backup_directory.mkdir()
    for artifact_name in _ARTIFACT_NAMES:
        (backup_directory / artifact_name).write_text(
            f"recovered:{artifact_name}\n",
            encoding="utf-8",
        )

    def failed_benchmark(argv: list[str]) -> int:
        print(json.dumps({"benchmark_failed_closed": True, "error_class": "TestError"}))
        return 1

    stdout = io.StringIO()
    result = csv_evidence.run_benchmark_cli_with_complete_csv(
        ["--output-dir", str(final_directory)],
        benchmark_cli=failed_benchmark,
        stdout=stdout,
    )

    assert result == 1
    assert sorted(path.name for path in final_directory.iterdir()) == sorted(
        _ARTIFACT_NAMES
    )
    assert (final_directory / "benchmark_report.json").read_text(
        encoding="utf-8"
    ).startswith("recovered:")
    assert _publication_residue(tmp_path, final_directory.name) == []
