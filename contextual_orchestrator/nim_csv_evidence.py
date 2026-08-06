"""Complete and transactionally publish NIM benchmark evidence artifacts.

The benchmark report records ``models_used`` for every policy/task cell in
JSON. This optional, standard-library-only adapter copies that evidence into the
uploaded CSV as deterministic JSON so spreadsheet consumers retain the exact
step, role, agent, and model identity required for audit and replay.

The adapter is intentionally lazy: importing :mod:`contextual_orchestrator`
does not import this module or mutate the benchmark implementation. The NIM CLI
composition root invokes it only for the benchmark command. The wrapper writes,
validates, enriches, and secret-checks the complete artifact set in a hidden
sibling staging directory before publishing the directory as one unit.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Callable, TextIO

from .nim_benchmark import run_benchmark_cli

DEFAULT_BENCHMARK_OUTPUT_DIRECTORY = Path("benchmark_artifacts")
_ASSIGNMENT_FIELDS = ("step_id", "role", "agent_id", "model_id")
_CELL_IDENTITY_FIELDS = ("policy_name", "task_id")
_ARTIFACT_FILENAMES = (
    "benchmark_report.json",
    "benchmark_cells.csv",
    "benchmark_summary.md",
)
_ARTIFACT_PATH_KEYS = {
    "json_path": "benchmark_report.json",
    "csv_path": "benchmark_cells.csv",
    "markdown_path": "benchmark_summary.md",
}


class CsvEvidenceError(RuntimeError):
    """The JSON, CSV, and Markdown files cannot form one complete evidence set."""


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


def _normalized_output_directory(output_directory: Path) -> Path:
    """Return a safe absolute final directory rooted at its resolved parent."""
    expanded = output_directory.expanduser()
    if expanded.name in {"", ".", ".."}:
        raise CsvEvidenceError("output directory must name a dedicated artifact directory")
    parent = expanded.parent.resolve()
    final_directory = parent / expanded.name
    if final_directory.is_symlink():
        raise CsvEvidenceError("output directory must not be a symbolic link")
    if final_directory.exists() and not final_directory.is_dir():
        raise CsvEvidenceError("output directory path must be a directory")
    return final_directory


def _remove_path(path: Path) -> None:
    """Remove one private publication path without following symbolic links."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _publication_residue(final_directory: Path, residue_kind: str) -> list[Path]:
    """Return sorted hidden staging or backup paths for one final directory."""
    return sorted(
        final_directory.parent.glob(
            f".{final_directory.name}.{residue_kind}-*"
        )
    )


def _recover_interrupted_publication(final_directory: Path) -> None:
    """Recover one crash backup and remove abandoned staging directories.

    A portable replacement of an existing non-empty directory requires two
    same-filesystem renames: final to backup, then staging to final. A process or
    host crash between those renames can leave the final name absent and one
    hidden backup present. The next run restores that sole backup before doing
    any benchmark work. Multiple backups are ambiguous and therefore fail
    closed rather than guessing which evidence set is authoritative.
    """
    for staging_path in _publication_residue(final_directory, "staging"):
        _remove_path(staging_path)

    backups = _publication_residue(final_directory, "backup")
    if len(backups) > 1:
        raise CsvEvidenceError(
            "multiple benchmark publication backups require operator review"
        )
    if not backups:
        return
    backup_path = backups[0]
    if final_directory.exists():
        _remove_path(backup_path)
    else:
        os.replace(backup_path, final_directory)


def _argv_with_output_directory(argv: list[str], output_directory: Path) -> list[str]:
    """Return CLI arguments with exactly one controlled staging output path."""
    rewritten: list[str] = []
    found = False
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--output-dir":
            if found:
                raise CsvEvidenceError("--output-dir may be supplied only once")
            if index + 1 >= len(argv):
                raise CsvEvidenceError("--output-dir requires a value")
            rewritten.extend(("--output-dir", str(output_directory)))
            found = True
            index += 2
            continue
        if argument.startswith("--output-dir="):
            if found:
                raise CsvEvidenceError("--output-dir may be supplied only once")
            rewritten.append(f"--output-dir={output_directory}")
            found = True
            index += 1
            continue
        rewritten.append(argument)
        index += 1
    if not found:
        rewritten.extend(("--output-dir", str(output_directory)))
    return rewritten


def _validate_complete_artifact_directory(staging_directory: Path) -> None:
    """Require exactly three regular, non-empty, fully enriched artifacts."""
    actual_names = sorted(path.name for path in staging_directory.iterdir())
    if actual_names != sorted(_ARTIFACT_FILENAMES):
        raise CsvEvidenceError(
            "staged benchmark directory must contain exactly JSON, CSV, and Markdown artifacts"
        )
    for artifact_name in _ARTIFACT_FILENAMES:
        artifact_path = staging_directory / artifact_name
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise CsvEvidenceError("staged benchmark artifacts must be regular files")
        if artifact_path.stat().st_size == 0:
            raise CsvEvidenceError("staged benchmark artifacts must not be empty")
    with (staging_directory / "benchmark_cells.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        fieldnames = list(csv.DictReader(handle).fieldnames or [])
    if "models_used_json" not in fieldnames:
        raise CsvEvidenceError("staged benchmark CSV lacks model-assignment evidence")


def _restore_backup_after_failure(
    final_directory: Path,
    backup_directory: Path | None,
) -> None:
    """Restore the prior complete set after an ordinary publication failure."""
    if backup_directory is None:
        _remove_path(final_directory)
        return
    if final_directory.exists():
        _remove_path(final_directory)
    if backup_directory.exists():
        os.replace(backup_directory, final_directory)


def _publish_staged_directory(
    staging_directory: Path,
    final_directory: Path,
) -> None:
    """Publish a complete staged directory with rollback for ordinary failures."""
    backup_directory: Path | None = None
    if final_directory.exists():
        backup_directory = final_directory.parent / (
            f".{final_directory.name}.backup-{uuid.uuid4().hex}"
        )
        if backup_directory.exists():
            raise CsvEvidenceError("generated benchmark backup path already exists")
        os.replace(final_directory, backup_directory)
    try:
        os.replace(staging_directory, final_directory)
        if backup_directory is not None:
            shutil.rmtree(backup_directory)
    except BaseException as publication_error:
        try:
            _restore_backup_after_failure(final_directory, backup_directory)
        except BaseException as restoration_error:
            raise CsvEvidenceError(
                "benchmark publication failed and the prior artifact set could not be restored"
            ) from restoration_error
        raise publication_error


def _rewrite_success_output(
    buffered_output: str,
    final_directory: Path,
) -> str:
    """Replace private staging paths in the success payload with final paths."""
    try:
        payload = json.loads(buffered_output)
    except json.JSONDecodeError as exc:
        raise CsvEvidenceError("benchmark success output must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CsvEvidenceError("benchmark success output must be a JSON object")
    artifact_paths = payload.get("artifact_paths")
    if not isinstance(artifact_paths, dict):
        raise CsvEvidenceError("benchmark success output requires artifact_paths")
    payload["artifact_paths"] = {
        key: str(final_directory / filename)
        for key, filename in _ARTIFACT_PATH_KEYS.items()
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write_fail_closed_result(stdout: TextIO, error: BaseException) -> None:
    """Write one bounded fail-closed result without exposing staged contents."""
    stdout.write(
        json.dumps(
            {
                "benchmark_failed_closed": True,
                "error_class": type(error).__name__,
                "error_message": str(error)[:500],
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def run_benchmark_cli_with_complete_csv(
    argv: list[str],
    *,
    benchmark_cli: Callable[[list[str]], int] = run_benchmark_cli,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run, enrich, and transactionally publish one complete evidence set.

    The benchmark runs in a hidden sibling staging directory. A successful
    result is emitted only after JSON/CSV identity validation, deterministic CSV
    assignment enrichment, complete-set validation, and directory publication.
    Fresh-target failures expose no final directory; replacement failures restore
    the prior complete set; temporary staging and ordinary rollback residue are
    removed. Benchmark failures are passed through unchanged.

    The portable crash contract is narrower than the ordinary rollback contract:
    replacing an existing non-empty directory takes two atomic renames, leaving
    an unavoidable crash window between backup creation and final publication.
    A later invocation restores a sole hidden backup before running. Ambiguous
    multiple backups fail closed for operator review.
    """
    staging_directory: Path | None = None
    benchmark_output = io.StringIO()
    try:
        requested_directory = output_directory_from_argv(argv)
        final_directory = _normalized_output_directory(requested_directory)
        final_directory.parent.mkdir(parents=True, exist_ok=True)
        _recover_interrupted_publication(final_directory)
        staging_directory = Path(
            tempfile.mkdtemp(
                dir=final_directory.parent,
                prefix=f".{final_directory.name}.staging-",
            )
        )
        staged_argv = _argv_with_output_directory(argv, staging_directory)
        with contextlib.redirect_stdout(benchmark_output):
            exit_code = benchmark_cli(staged_argv)
        if exit_code != 0:
            stdout.write(benchmark_output.getvalue())
            return exit_code

        enrich_benchmark_cell_csv(
            staging_directory / "benchmark_report.json",
            staging_directory / "benchmark_cells.csv",
        )
        _validate_complete_artifact_directory(staging_directory)
        success_output = _rewrite_success_output(
            benchmark_output.getvalue(),
            final_directory,
        )
        _publish_staged_directory(staging_directory, final_directory)
        staging_directory = None
        stdout.write(success_output)
        return 0
    except (CsvEvidenceError, OSError, UnicodeError, csv.Error) as error:
        _write_fail_closed_result(stdout, error)
        return 1
    finally:
        if staging_directory is not None:
            _remove_path(staging_directory)
