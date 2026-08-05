"""Edge coverage for the NIM CSV evidence adapter's fail-closed branches."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from contextual_orchestrator import nim_csv_evidence as csv_evidence


def _write_valid_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["policy_name", "task_id"])
        writer.writeheader()
        writer.writerows(rows)


def _write_valid_report(path: Path, cells: list[object]) -> None:
    path.write_text(
        json.dumps({"evaluation": {"evaluation_cells": cells}}),
        encoding="utf-8",
    )


def test_report_rejects_non_object_root_and_non_object_cells(tmp_path: Path) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    _write_valid_csv(csv_path, [])

    report_path.write_text("[]", encoding="utf-8")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="evaluation.evaluation_cells"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    _write_valid_report(report_path, ["not-an-object"])
    with pytest.raises(csv_evidence.CsvEvidenceError, match="report cell must be an object"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)


@pytest.mark.parametrize(
    "cell",
    [
        {"policy_name": "", "task_id": "task_one", "models_used": []},
        {"policy_name": "route_once", "task_id": "", "models_used": []},
        {"policy_name": 7, "task_id": "task_one", "models_used": []},
    ],
)
def test_report_rejects_empty_or_non_string_cell_identity(
    tmp_path: Path,
    cell: dict[str, object],
) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    _write_valid_report(report_path, [cell])
    _write_valid_csv(csv_path, [])
    with pytest.raises(csv_evidence.CsvEvidenceError, match="requires non-empty"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)


def test_csv_rejects_invalid_utf8_empty_header_and_empty_identity(tmp_path: Path) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    _write_valid_report(report_path, [])

    csv_path.write_bytes(b"\xff\xfe")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="not readable"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    csv_path.write_text("", encoding="utf-8")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="identity columns"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    _write_valid_report(
        report_path,
        [{"policy_name": "route_once", "task_id": "task_one", "models_used": []}],
    )
    _write_valid_csv(csv_path, [{"policy_name": "", "task_id": "task_one"}])
    with pytest.raises(csv_evidence.CsvEvidenceError, match="CSV cell requires non-empty"):
        csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)


def test_empty_report_and_csv_are_enriched_deterministically(tmp_path: Path) -> None:
    report_path = tmp_path / "benchmark_report.json"
    csv_path = tmp_path / "benchmark_cells.csv"
    _write_valid_report(report_path, [])
    _write_valid_csv(csv_path, [])

    csv_evidence.enrich_benchmark_cell_csv(report_path, csv_path)

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["policy_name", "task_id", "models_used_json"]
        assert list(reader) == []
