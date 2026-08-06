"""Regression tests for complete, fail-closed NIM CSV assignment evidence."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from contextual_orchestrator import nim_csv_evidence as csv_evidence


def _write_report(path: Path, cells: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"evaluation": {"evaluation_cells": cells}}),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, str]], *, include_assignment: bool = False) -> None:
    fieldnames = ["policy_name", "task_id", "task_score"]
    if include_assignment:
        fieldnames.append("models_used_json")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _model_use(step_id: str, model_id: str) -> dict[str, str]:
    return {
        "step_id": step_id,
        "role": "worker",
        "agent_id": f"agent_{step_id}",
        "model_id": model_id,
    }


def test_enrich_csv_adds_deterministic_role_and_model_assignment_evidence(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    cells = [
        {
            "policy_name": "conduct_bounded",
            "task_id": "locked_task_two",
            "models_used": [
                _model_use("step_two", "vendor/model-b"),
                _model_use("step_one", "vendor/model-a"),
            ],
        },
        {
            "policy_name": "route_once",
            "task_id": "locked_task_one",
            "models_used": [],
        },
    ]
    _write_report(report_path, cells)
    _write_csv(
        csv_path,
        [
            {
                "policy_name": "route_once",
                "task_id": "locked_task_one",
                "task_score": "1.0",
            },
            {
                "policy_name": "conduct_bounded",
                "task_id": "locked_task_two",
                "task_score": "0.5",
            },
        ],
    )

    csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "policy_name",
        "task_id",
        "task_score",
        "models_used_json",
    ]
    assert json.loads(rows[0]["models_used_json"]) == []
    assert json.loads(rows[1]["models_used_json"]) == cells[0]["models_used"]
    assert rows[1]["models_used_json"] == json.dumps(
        cells[0]["models_used"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    # Re-enrichment is idempotent and replaces rather than duplicates the column.
    first_bytes = csv_path.read_bytes()
    csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)
    assert csv_path.read_bytes() == first_bytes


@pytest.mark.parametrize(
    ("report", "error_match"),
    [
        ({}, "evaluation.evaluation_cells"),
        ({"evaluation": {"evaluation_cells": "not-a-list"}}, "evaluation.evaluation_cells"),
        (
            {
                "evaluation": {
                    "evaluation_cells": [
                        {"policy_name": "route_once", "task_id": "task_one"}
                    ]
                }
            },
            "models_used",
        ),
        (
            {
                "evaluation": {
                    "evaluation_cells": [
                        {
                            "policy_name": "route_once",
                            "task_id": "task_one",
                            "models_used": ["not-an-object"],
                        }
                    ]
                }
            },
            "model assignment",
        ),
        (
            {
                "evaluation": {
                    "evaluation_cells": [
                        {
                            "policy_name": "route_once",
                            "task_id": "task_one",
                            "models_used": [
                                {
                                    "step_id": "step_one",
                                    "role": "worker",
                                    "agent_id": "agent_one",
                                    "model_id": "",
                                }
                            ],
                        }
                    ]
                }
            },
            "model_id",
        ),
    ],
)
def test_enrich_csv_rejects_malformed_report_without_replacing_existing_csv(
    tmp_path: Path,
    report: dict[str, object],
    error_match: str,
) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    _write_csv(
        csv_path,
        [{"policy_name": "route_once", "task_id": "task_one", "task_score": "1"}],
    )
    original = csv_path.read_bytes()

    with pytest.raises(csv_evidence.CsvEvidenceError, match=error_match):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    assert csv_path.read_bytes() == original


def test_enrich_csv_rejects_duplicate_or_mismatched_cell_keys(tmp_path: Path) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    duplicated_cell = {
        "policy_name": "route_once",
        "task_id": "task_one",
        "models_used": [],
    }
    _write_report(report_path, [duplicated_cell, duplicated_cell])
    _write_csv(
        csv_path,
        [{"policy_name": "route_once", "task_id": "task_one", "task_score": "1"}],
    )
    with pytest.raises(csv_evidence.CsvEvidenceError, match="duplicate report cell"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    _write_report(report_path, [duplicated_cell])
    _write_csv(
        csv_path,
        [
            {"policy_name": "route_once", "task_id": "task_one", "task_score": "1"},
            {"policy_name": "route_once", "task_id": "task_one", "task_score": "1"},
        ],
    )
    with pytest.raises(csv_evidence.CsvEvidenceError, match="duplicate CSV cell"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    _write_csv(
        csv_path,
        [{"policy_name": "route_once", "task_id": "task_two", "task_score": "1"}],
    )
    with pytest.raises(csv_evidence.CsvEvidenceError, match="cell identity mismatch"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)


def test_enrich_csv_rejects_missing_identity_columns_and_invalid_json(tmp_path: Path) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    report_path.write_text("{not json", encoding="utf-8")
    csv_path.write_text("policy_name\nroute_once\n", encoding="utf-8")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="valid JSON"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    _write_report(
        report_path,
        [{"policy_name": "route_once", "task_id": "task_one", "models_used": []}],
    )
    with pytest.raises(csv_evidence.CsvEvidenceError, match="task_id"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)


def test_output_directory_parser_supports_default_split_and_equals_forms() -> None:
    assert csv_evidence.output_directory_from_argv(["--dry-run"]) == Path(
        "benchmark_artifacts"
    )
    assert csv_evidence.output_directory_from_argv(
        ["--dry-run", "--output-dir", "custom evidence"]
    ) == Path("custom evidence")
    assert csv_evidence.output_directory_from_argv(
        ["--output-dir=equals-evidence"]
    ) == Path("equals-evidence")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="non-empty"):
        csv_evidence.output_directory_from_argv(["--output-dir="])
    with pytest.raises(csv_evidence.CsvEvidenceError, match="requires a value"):
        csv_evidence.output_directory_from_argv(["--output-dir"])


def test_cli_wrapper_publishes_success_only_after_csv_enrichment(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"

    def benchmark_cli(argv: list[str]) -> int:
        staged_output_dir = csv_evidence.output_directory_from_argv(argv)
        staged_output_dir.mkdir()
        _write_report(
            staged_output_dir / "benchmark_report.json",
            [{"policy_name": "route_once", "task_id": "task_one", "models_used": []}],
        )
        _write_csv(
            staged_output_dir / "benchmark_cells.csv",
            [{"policy_name": "route_once", "task_id": "task_one", "task_score": "1"}],
        )
        (staged_output_dir / "benchmark_summary.md").write_text(
            "# summary\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "run_mode": "dry_run",
                    "artifact_paths": {
                        "json_path": str(staged_output_dir / "benchmark_report.json"),
                        "csv_path": str(staged_output_dir / "benchmark_cells.csv"),
                        "markdown_path": str(staged_output_dir / "benchmark_summary.md"),
                    },
                }
            )
        )
        return 0

    stdout = io.StringIO()
    result = csv_evidence.run_benchmark_cli_with_complete_csv(
        ["--output-dir", str(output_dir)],
        benchmark_cli=benchmark_cli,
        stdout=stdout,
    )

    assert result == 0
    payload = json.loads(stdout.getvalue())
    assert payload["run_mode"] == "dry_run"
    assert payload["artifact_paths"] == {
        "json_path": str(output_dir / "benchmark_report.json"),
        "csv_path": str(output_dir / "benchmark_cells.csv"),
        "markdown_path": str(output_dir / "benchmark_summary.md"),
    }
    assert "models_used_json" in (output_dir / "benchmark_cells.csv").read_text(
        encoding="utf-8"
    )


def test_cli_wrapper_preserves_benchmark_failure_and_fails_closed_on_enrichment(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()

    def failed_benchmark_cli(argv: list[str]) -> int:
        print(json.dumps({"benchmark_failed_closed": True, "error_class": "TestError"}))
        return 1

    assert (
        csv_evidence.run_benchmark_cli_with_complete_csv(
            [], benchmark_cli=failed_benchmark_cli, stdout=stdout
        )
        == 1
    )
    assert json.loads(stdout.getvalue())["error_class"] == "TestError"

    stdout = io.StringIO()

    def incomplete_success(argv: list[str]) -> int:
        print(json.dumps({"run_mode": "dry_run"}))
        return 0

    result = csv_evidence.run_benchmark_cli_with_complete_csv(
        ["--output-dir", str(tmp_path / "missing")],
        benchmark_cli=incomplete_success,
        stdout=stdout,
    )
    failure = json.loads(stdout.getvalue())
    assert result == 1
    assert failure["benchmark_failed_closed"] is True
    assert failure["error_class"] in {"CsvEvidenceError", "FileNotFoundError"}
    assert "run_mode" not in failure
