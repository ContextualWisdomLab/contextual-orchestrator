"""Complete NIM benchmark CSV artifacts with role and model assignments.

The benchmark report already records ``models_used`` for every policy/task cell
in JSON.  This optional, standard-library-only adapter copies that evidence into
the uploaded CSV as deterministic JSON so spreadsheet consumers do not lose the
step, role, agent, or model identity that buyers need for audit and replay.

The adapter is intentionally lazy: importing :mod:`contextual_orchestrator`
does not import this module or mutate the benchmark implementation.  The NIM CLI
composition root invokes it only after the benchmark itself succeeds.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Callable, TextIO

from .nim_benchmark import run_benchmark_cli

DEFAULT_BENCHMARK_OUTPUT_DIRECTORY = Path("benchmark_artifacts")
_ASSIGNMENT_FIELDS = ("step_id", "role", "agent_id", "model_id")
_CELL_IDENTITY_FIELDS = ("policy_name", "task_id")


class CsvEvidenceError(RuntimeError):
    """The JSON report and CSV cells cannot form one complete evidence set."""


def _cell_identity(cell: object, source_label: str) -> tuple[str, str]:
    """Return one non-empty policy/task identity from a report or CSV row."""
    if not isinstance(cell, dict):
        raise CsvEvidenceError(f"{source_label} cell must be an object")
    values: list[str] = []
    for field_name in _CELL_IDENTITY_FIELDS:
        value = cell.get(field_name)
        if not isinstance(value, str) or not value:
            raise CsvEvidenceError(
                f"{source_label} cell requires non-empty {field_name}"
            )
        values.append(value)
    return values[0], values[1]


def _models_used_json(value: object) -> str:
    """Validate and deterministically serialize one cell's model assignments."""
    if not isinstance(value, list):
        raise CsvEvidenceError("report cell models_used must be a list")
    normalized: list[dict[str, str]] = []
    for assignment in value:
        if not isinstance(assignment, dict):
            raise CsvEvidenceError("each model assignment must be an object")
        normalized_assignment: dict[str, str] = {}
        for field_name in _ASSIGNMENT_FIELDS:
            field_value = assignment.get(field_name)
            if not isinstance(field_value, str) or not field_value:
                raise CsvEvidenceError(
                    f"model assignment requires non-empty {field_name}"
                )
            normalized_assignment[field_name] = field_value
        normalized.append(normalized_assignment)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _report_assignment_map(report_path: Path) -> dict[tuple[str, str], str]:
    """Load the report and index validated assignment evidence by cell identity."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CsvEvidenceError("benchmark report must contain valid JSON") from exc
    evaluation = report.get("evaluation") if isinstance(report, dict) else None
    cells = evaluation.get("evaluation_cells") if isinstance(evaluation, dict) else None
    if not isinstance(cells, list):
        raise CsvEvidenceError(
            "benchmark report requires evaluation.evaluation_cells as a list"
        )

    assignments: dict[tuple[str, str], str] = {}
    for cell in cells:
        identity = _cell_identity(cell, "report")
        if identity in assignments:
            raise CsvEvidenceError(
                "duplicate report cell identity: " + "/".join(identity)
            )
        assignments[identity] = _models_used_json(cell.get("models_used"))
    return assignments


def _csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read CSV rows and validate that each cell identity occurs exactly once."""
    try:
        with csv_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise CsvEvidenceError("benchmark cell CSV is not readable") from exc
    missing_fields = [
        field_name
        for field_name in _CELL_IDENTITY_FIELDS
        if field_name not in fieldnames
    ]
    if missing_fields:
        raise CsvEvidenceError(
            "benchmark cell CSV is missing identity columns: "
            + ", ".join(missing_fields)
        )

    seen: set[tuple[str, str]] = set()
    for row in rows:
        identity = _cell_identity(row, "CSV")
        if identity in seen:
            raise CsvEvidenceError(
                "duplicate CSV cell identity: " + "/".join(identity)
            )
        seen.add(identity)
    return fieldnames, rows


def enrich_benchmark_cell_csv(
    report_path: str | os.PathLike[str],
    csv_path: str | os.PathLike[str],
) -> None:
    """Atomically add deterministic ``models_used_json`` to every CSV cell.

    Args:
        report_path: Path to the benchmark's authoritative JSON report.
        csv_path: Path to the benchmark cell CSV written by the same run.

    Raises:
        CsvEvidenceError: If either artifact is malformed, duplicated, or does
            not describe exactly the same policy/task cells.
        OSError: If an artifact cannot be read or the atomic replacement fails.
    """
    report_file = Path(report_path)
    csv_file = Path(csv_path)
    assignments = _report_assignment_map(report_file)
    fieldnames, rows = _csv_rows(csv_file)
    csv_identities = {_cell_identity(row, "CSV") for row in rows}
    if csv_identities != set(assignments):
        missing_from_csv = sorted(set(assignments) - csv_identities)
        missing_from_report = sorted(csv_identities - set(assignments))
        raise CsvEvidenceError(
            "benchmark JSON/CSV cell identity mismatch; "
            f"missing_from_csv={missing_from_csv}; "
            f"missing_from_report={missing_from_report}"
        )

    output_fields = [
        field_name for field_name in fieldnames if field_name != "models_used_json"
    ]
    output_fields.append("models_used_json")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=output_fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        enriched_row = dict(row)
        enriched_row["models_used_json"] = assignments[_cell_identity(row, "CSV")]
        writer.writerow(enriched_row)

    csv_mode = stat.S_IMODE(csv_file.stat().st_mode)
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=csv_file.parent,
        prefix=f".{csv_file.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as temporary:
            temporary.write(buffer.getvalue())
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, csv_mode)
        os.replace(temporary_path, csv_file)
    finally:
        temporary_path.unlink(missing_ok=True)


def output_directory_from_argv(argv: list[str]) -> Path:
    """Return the NIM CLI output directory without accepting any secret input."""
    for index, argument in enumerate(argv):
        if argument == "--output-dir":
            if index + 1 >= len(argv):
                raise CsvEvidenceError("--output-dir requires a value")
            return Path(argv[index + 1])
        if argument.startswith("--output-dir="):
            value = argument.split("=", 1)[1]
            if not value:
                raise CsvEvidenceError("--output-dir requires a non-empty value")
            return Path(value)
    return DEFAULT_BENCHMARK_OUTPUT_DIRECTORY


def run_benchmark_cli_with_complete_csv(
    argv: list[str],
    *,
    benchmark_cli: Callable[[list[str]], int] = run_benchmark_cli,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run the benchmark and publish success only after CSV evidence is complete.

    The wrapped benchmark's output is buffered.  A successful result is emitted
    only after the JSON and CSV cell identities match and every CSV row contains
    deterministic role/model assignment evidence.  Benchmark failures are
    passed through unchanged; enrichment failures return a new fail-closed JSON
    result and suppress the premature success payload.
    """
    benchmark_output = io.StringIO()
    with contextlib.redirect_stdout(benchmark_output):
        exit_code = benchmark_cli(argv)
    if exit_code != 0:
        stdout.write(benchmark_output.getvalue())
        return exit_code

    try:
        output_directory = output_directory_from_argv(argv)
        enrich_benchmark_cell_csv(
            output_directory / "benchmark_report.json",
            output_directory / "benchmark_cells.csv",
        )
    except (CsvEvidenceError, OSError) as exc:
        stdout.write(
            json.dumps(
                {
                    "benchmark_failed_closed": True,
                    "error_class": type(exc).__name__,
                    "error_message": str(exc),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return 1

    stdout.write(benchmark_output.getvalue())
    return 0
