"""Edge coverage for transactional NIM benchmark artifact publication."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from contextual_orchestrator import nim_csv_evidence as csv_evidence

_ARTIFACT_NAMES = (
    "benchmark_report.json",
    "benchmark_cells.csv",
    "benchmark_summary.md",
)


def _write_valid_published_directory(directory: Path, marker: str) -> None:
    """Write three non-empty files with enriched CSV evidence."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "benchmark_report.json").write_text(
        json.dumps({"marker": marker}),
        encoding="utf-8",
    )
    (directory / "benchmark_cells.csv").write_text(
        "policy_name,task_id,models_used_json\r\nroute_once,task_one,[]\r\n",
        encoding="utf-8",
    )
    (directory / "benchmark_summary.md").write_text(
        f"# {marker}\n",
        encoding="utf-8",
    )


def test_output_target_rejects_dot_symbolic_link_and_regular_file(
    tmp_path: Path,
) -> None:
    """Publication accepts only a dedicated non-symlink directory path."""
    with pytest.raises(csv_evidence.CsvEvidenceError, match="dedicated"):
        csv_evidence._normalized_output_directory(Path("."))

    target = tmp_path / "target_directory"
    target.mkdir()
    linked = tmp_path / "linked_evidence"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(csv_evidence.CsvEvidenceError, match="symbolic link"):
        csv_evidence._normalized_output_directory(linked)

    regular_file = tmp_path / "evidence_file"
    regular_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="must be a directory"):
        csv_evidence._normalized_output_directory(regular_file)


def test_remove_path_handles_file_directory_symbolic_link_and_missing(
    tmp_path: Path,
) -> None:
    """Private cleanup never follows links and treats absence as success."""
    regular_file = tmp_path / "temporary_file"
    regular_file.write_text("temporary", encoding="utf-8")
    csv_evidence._remove_path(regular_file)
    assert not regular_file.exists()

    directory = tmp_path / "temporary_directory"
    directory.mkdir()
    (directory / "child").write_text("temporary", encoding="utf-8")
    csv_evidence._remove_path(directory)
    assert not directory.exists()

    target = tmp_path / "target_directory"
    target.mkdir()
    linked = tmp_path / "temporary_link"
    linked.symlink_to(target, target_is_directory=True)
    csv_evidence._remove_path(linked)
    assert not linked.exists()
    assert target.exists()

    csv_evidence._remove_path(tmp_path / "already_missing")


def test_recovery_cleans_staging_rejects_ambiguity_and_discards_stale_backup(
    tmp_path: Path,
) -> None:
    """Recovery is deterministic for staging and backup residue."""
    final_directory = tmp_path / "buyer_evidence"
    staging = tmp_path / ".buyer_evidence.staging-abandoned"
    staging.mkdir()
    csv_evidence._recover_interrupted_publication(final_directory)
    assert not staging.exists()

    first_backup = tmp_path / ".buyer_evidence.backup-one"
    second_backup = tmp_path / ".buyer_evidence.backup-two"
    first_backup.mkdir()
    second_backup.mkdir()
    with pytest.raises(csv_evidence.CsvEvidenceError, match="multiple"):
        csv_evidence._recover_interrupted_publication(final_directory)
    first_backup.rmdir()
    second_backup.rmdir()

    _write_valid_published_directory(final_directory, "current")
    stale_backup = tmp_path / ".buyer_evidence.backup-stale"
    _write_valid_published_directory(stale_backup, "stale")
    csv_evidence._recover_interrupted_publication(final_directory)
    assert final_directory.exists()
    assert not stale_backup.exists()


def test_staging_argv_rewrite_supports_all_forms_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    """Only one user output option is replaced by the private staging path."""
    staging = tmp_path / "private_staging"
    assert csv_evidence._argv_with_output_directory(["--dry-run"], staging) == [
        "--dry-run",
        "--output-dir",
        str(staging),
    ]
    assert csv_evidence._argv_with_output_directory(
        ["--dry-run", "--output-dir=public"],
        staging,
    ) == ["--dry-run", f"--output-dir={staging}"]
    assert csv_evidence._argv_with_output_directory(
        ["--output-dir", "public", "--dry-run"],
        staging,
    ) == ["--output-dir", str(staging), "--dry-run"]

    with pytest.raises(csv_evidence.CsvEvidenceError, match="only once"):
        csv_evidence._argv_with_output_directory(
            ["--output-dir", "one", "--output-dir=two"],
            staging,
        )
    with pytest.raises(csv_evidence.CsvEvidenceError, match="only once"):
        csv_evidence._argv_with_output_directory(
            ["--output-dir=one", "--output-dir", "two"],
            staging,
        )
    with pytest.raises(csv_evidence.CsvEvidenceError, match="requires a value"):
        csv_evidence._argv_with_output_directory(["--output-dir"], staging)


def test_complete_directory_validation_rejects_shape_link_empty_and_plain_csv(
    tmp_path: Path,
) -> None:
    """Every staged set must contain exactly three regular enriched files."""
    wrong_shape = tmp_path / "wrong_shape"
    wrong_shape.mkdir()
    (wrong_shape / "unexpected").write_text("x", encoding="utf-8")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="exactly JSON"):
        csv_evidence._validate_complete_artifact_directory(wrong_shape)

    linked_shape = tmp_path / "linked_shape"
    linked_shape.mkdir()
    (linked_shape / "benchmark_report.json").write_text("{}", encoding="utf-8")
    (linked_shape / "benchmark_cells.csv").write_text(
        "policy_name,task_id,models_used_json\n",
        encoding="utf-8",
    )
    link_target = tmp_path / "summary_target"
    link_target.write_text("# target\n", encoding="utf-8")
    (linked_shape / "benchmark_summary.md").symlink_to(link_target)
    with pytest.raises(csv_evidence.CsvEvidenceError, match="regular files"):
        csv_evidence._validate_complete_artifact_directory(linked_shape)

    empty_shape = tmp_path / "empty_shape"
    _write_valid_published_directory(empty_shape, "valid")
    (empty_shape / "benchmark_summary.md").write_text("", encoding="utf-8")
    with pytest.raises(csv_evidence.CsvEvidenceError, match="must not be empty"):
        csv_evidence._validate_complete_artifact_directory(empty_shape)

    plain_csv = tmp_path / "plain_csv"
    _write_valid_published_directory(plain_csv, "valid")
    (plain_csv / "benchmark_cells.csv").write_text(
        "policy_name,task_id\nroute_once,task_one\n",
        encoding="utf-8",
    )
    with pytest.raises(csv_evidence.CsvEvidenceError, match="model-assignment"):
        csv_evidence._validate_complete_artifact_directory(plain_csv)


def test_restore_helper_handles_fresh_partial_missing_backup_and_partial_publish(
    tmp_path: Path,
) -> None:
    """Rollback removes a fresh partial and restores a present prior backup."""
    fresh_partial = tmp_path / "fresh_partial"
    _write_valid_published_directory(fresh_partial, "partial")
    csv_evidence._restore_backup_after_failure(fresh_partial, None)
    assert not fresh_partial.exists()

    final_directory = tmp_path / "buyer_evidence"
    missing_backup = tmp_path / ".buyer_evidence.backup-missing"
    csv_evidence._restore_backup_after_failure(final_directory, missing_backup)
    assert not final_directory.exists()

    _write_valid_published_directory(final_directory, "partial")
    backup_directory = tmp_path / ".buyer_evidence.backup-prior"
    _write_valid_published_directory(backup_directory, "prior")
    csv_evidence._restore_backup_after_failure(final_directory, backup_directory)
    assert "prior" in (final_directory / "benchmark_report.json").read_text(
        encoding="utf-8"
    )
    assert not backup_directory.exists()


def test_publish_replaces_prior_set_and_removes_backup(tmp_path: Path) -> None:
    """Successful replacement exposes the new set and deletes its hidden backup."""
    final_directory = tmp_path / "buyer_evidence"
    staging_directory = tmp_path / ".buyer_evidence.staging-ready"
    _write_valid_published_directory(final_directory, "prior")
    _write_valid_published_directory(staging_directory, "new")

    csv_evidence._publish_staged_directory(staging_directory, final_directory)

    assert "new" in (final_directory / "benchmark_report.json").read_text(
        encoding="utf-8"
    )
    assert not staging_directory.exists()
    assert list(tmp_path.glob(".buyer_evidence.backup-*")) == []


def test_publish_rejects_generated_backup_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-existing generated backup name fails closed before mutation."""
    final_directory = tmp_path / "buyer_evidence"
    staging_directory = tmp_path / ".buyer_evidence.staging-ready"
    _write_valid_published_directory(final_directory, "prior")
    _write_valid_published_directory(staging_directory, "new")
    monkeypatch.setattr(
        csv_evidence.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="fixed"),
    )
    collision = tmp_path / ".buyer_evidence.backup-fixed"
    collision.mkdir()

    with pytest.raises(csv_evidence.CsvEvidenceError, match="already exists"):
        csv_evidence._publish_staged_directory(staging_directory, final_directory)

    assert final_directory.exists()
    assert staging_directory.exists()


def test_publish_reports_irrecoverable_restoration_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure of both publication and rollback is surfaced as a domain error."""
    final_directory = tmp_path / "buyer_evidence"
    staging_directory = tmp_path / ".buyer_evidence.staging-ready"
    _write_valid_published_directory(final_directory, "prior")
    _write_valid_published_directory(staging_directory, "new")
    monkeypatch.setattr(
        csv_evidence.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="fixed"),
    )
    real_replace = os.replace
    call_count = 0

    def fail_publish_and_restore(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            real_replace(source, destination)
            return
        raise OSError("simulated publish or restoration failure")

    monkeypatch.setattr(csv_evidence.os, "replace", fail_publish_and_restore)
    with pytest.raises(csv_evidence.CsvEvidenceError, match="could not be restored"):
        csv_evidence._publish_staged_directory(staging_directory, final_directory)

    backup_directory = tmp_path / ".buyer_evidence.backup-fixed"
    assert backup_directory.exists()
    shutil.rmtree(backup_directory)
    shutil.rmtree(staging_directory)


def test_success_output_rewrite_rejects_malformed_payloads(tmp_path: Path) -> None:
    """A published success result must be a JSON object with artifact paths."""
    final_directory = tmp_path / "buyer_evidence"
    with pytest.raises(csv_evidence.CsvEvidenceError, match="valid JSON"):
        csv_evidence._rewrite_success_output("not-json", final_directory)
    with pytest.raises(csv_evidence.CsvEvidenceError, match="JSON object"):
        csv_evidence._rewrite_success_output("[]", final_directory)
    with pytest.raises(csv_evidence.CsvEvidenceError, match="artifact_paths"):
        csv_evidence._rewrite_success_output("{}", final_directory)
