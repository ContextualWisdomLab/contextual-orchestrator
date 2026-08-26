"""Contract tests for the NIM benchmark evidence boundary."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from contextual_orchestrator.nim_evidence import (
    NIM_EVIDENCE_SCHEMA_VERSION,
    NimEvidenceError,
    canonical_json_sha256,
    publish_artifact_set,
    validate_provenance,
    validate_task_manifest,
)


def _manifest() -> dict[str, object]:
    return {
        "schema_version": NIM_EVIDENCE_SCHEMA_VERSION,
        "tasks": [
            {
                "task_id": "locked_task",
                "prompt": "Answer.",
                "scorer": {"name": "exact_match", "version": "1"},
            }
        ],
    }


def _provenance() -> dict[str, str]:
    digest = "a" * 64
    return {
        "source_commit": "a" * 40,
        "catalog_snapshot_sha256": digest,
        "task_manifest_sha256": digest,
        "pricing_scenario_sha256": "unknown",
        "workflow_run_id": "offline_fixture",
        "evidence_status": "dry_run",
    }


def _artifacts() -> dict[str, bytes]:
    return {
        "benchmark_report.json": b"{}",
        "benchmark_cells.csv": b"task_id\nlocked_task\n",
        "benchmark_summary.md": b"# Evidence\n",
        "run_provenance.json": json.dumps(_provenance()).encode(),
    }


def test_manifest_and_provenance_are_deterministic_and_strict() -> None:
    manifest = _manifest()
    assert validate_task_manifest(manifest) is manifest
    assert canonical_json_sha256(manifest) == canonical_json_sha256(
        dict(reversed(list(manifest.items())))
    )
    assert validate_provenance(_provenance())["evidence_status"] == "dry_run"
    for invalid in (
        {},
        {**manifest, "schema_version": "future"},
        {**manifest, "tasks": []},
    ):
        with pytest.raises(NimEvidenceError):
            validate_task_manifest(invalid)
    duplicate = _manifest()
    duplicate["tasks"] = [duplicate["tasks"][0], duplicate["tasks"][0]]  # type: ignore[index]
    with pytest.raises(NimEvidenceError):
        validate_task_manifest(duplicate)
    with pytest.raises(NimEvidenceError):
        validate_provenance({**_provenance(), "source_commit": "not-a-hash"})
    with pytest.raises(NimEvidenceError):
        validate_provenance({**_provenance(), "pricing_scenario_sha256": "not-a-hash"})


@pytest.mark.parametrize(
    "task",
    [
        42,
        {"task_id": "", "prompt": "x", "scorer": {"name": "n", "version": "1"}},
        {"task_id": "id", "prompt": "", "scorer": {"name": "n", "version": "1"}},
        {"task_id": "id", "prompt": "x", "scorer": None},
        {"task_id": "id", "prompt": "x", "scorer": {"name": "", "version": "1"}},
    ],
)
def test_manifest_rejects_malformed_task_fields(task: object) -> None:
    with pytest.raises(NimEvidenceError):
        validate_task_manifest(
            {"schema_version": NIM_EVIDENCE_SCHEMA_VERSION, "tasks": [task]}
        )


def test_provenance_rejects_shape_and_empty_values() -> None:
    with pytest.raises(NimEvidenceError):
        validate_provenance([])
    with pytest.raises(NimEvidenceError):
        validate_provenance({**_provenance(), "workflow_run_id": ""})


def test_complete_set_replaces_prior_set_and_rejects_partial_set(
    tmp_path: Path,
) -> None:
    target = tmp_path / "nim_evidence"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    publish_artifact_set(target, _artifacts())
    assert {path.name for path in target.iterdir()} == set(_artifacts())
    with pytest.raises(NimEvidenceError):
        publish_artifact_set(tmp_path / "partial", {"benchmark_report.json": b"{}"})

    fresh = tmp_path / "fresh"
    previous_umask = os.umask(0o027)
    try:
        publish_artifact_set(fresh, _artifacts())
    finally:
        os.umask(previous_umask)
    assert fresh.is_dir()
    assert fresh.stat().st_mode & 0o777 == 0o750


def test_successful_replacement_preserves_mode_and_ignores_backup_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nim_evidence"
    target.mkdir(mode=0o750)
    real_rmtree = shutil.rmtree

    def fail_backup(path: str | os.PathLike[str]) -> None:
        if Path(path).name.startswith(".nim_evidence.backup-"):
            raise OSError("simulated cleanup failure")
        real_rmtree(path)

    monkeypatch.setattr("contextual_orchestrator.nim_evidence.shutil.rmtree", fail_backup)
    publish_artifact_set(target, _artifacts())
    assert target.stat().st_mode & 0o777 == 0o750
    assert (target / "benchmark_report.json").read_bytes() == b"{}"


def test_publication_rejects_invalid_payloads_and_targets(tmp_path: Path) -> None:
    empty = _artifacts()
    empty["benchmark_report.json"] = b""
    with pytest.raises(NimEvidenceError):
        publish_artifact_set(tmp_path / "empty", empty)
    malformed = _artifacts()
    malformed["run_provenance.json"] = b"not-json"
    with pytest.raises(NimEvidenceError, match="valid UTF-8 JSON"):
        publish_artifact_set(tmp_path / "malformed", malformed)
    regular_file = tmp_path / "regular"
    regular_file.write_text("x", encoding="utf-8")
    with pytest.raises(NimEvidenceError):
        publish_artifact_set(regular_file, _artifacts())
    symlink = tmp_path / "linked"
    symlink.symlink_to(regular_file)
    with pytest.raises(NimEvidenceError):
        publish_artifact_set(symlink, _artifacts())
    with pytest.raises(NimEvidenceError):
        publish_artifact_set(Path("."), _artifacts())


def test_publication_failure_restores_prior_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nim_evidence"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    real_replace = os.replace

    def fail_staging(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        if Path(source).name.startswith(".nim_evidence.staging-"):
            raise OSError("simulated publication failure")
        real_replace(source, destination)

    monkeypatch.setattr("contextual_orchestrator.nim_evidence.os.replace", fail_staging)
    with pytest.raises(OSError):
        publish_artifact_set(target, _artifacts())
    assert (target / "old.txt").read_text(encoding="utf-8") == "old"


def test_fresh_publication_failure_leaves_no_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nim_evidence"

    def fail_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr("contextual_orchestrator.nim_evidence.os.replace", fail_replace)
    with pytest.raises(OSError):
        publish_artifact_set(target, _artifacts())
    assert not target.exists()


def test_crash_residue_is_recovered_or_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "nim_evidence"
    abandoned = tmp_path / ".nim_evidence.staging-old"
    abandoned.mkdir()
    backup = tmp_path / ".nim_evidence.backup-old"
    backup.mkdir()
    (backup / "old.txt").write_text("old", encoding="utf-8")
    publish_artifact_set(target, _artifacts())
    assert not abandoned.exists()
    assert not backup.exists()

    first = tmp_path / ".ambiguous.backup-one"
    second = tmp_path / ".ambiguous.backup-two"
    first.mkdir()
    second.mkdir()
    with pytest.raises(NimEvidenceError):
        publish_artifact_set(tmp_path / "ambiguous", _artifacts())


def test_crash_recovery_treats_glob_metacharacters_as_literal(tmp_path: Path) -> None:
    target = tmp_path / "nim[evidence]"
    backup = tmp_path / ".nim[evidence].backup-old"
    backup.mkdir()
    unrelated = tmp_path / ".nime.backup-unrelated"
    unrelated.mkdir()

    publish_artifact_set(target, _artifacts())

    assert target.is_dir()
    assert not backup.exists()
    assert unrelated.is_dir()


def test_existing_final_discards_stale_backup(tmp_path: Path) -> None:
    target = tmp_path / "nim_evidence"
    target.mkdir()
    backup = tmp_path / ".nim_evidence.backup-old"
    backup.mkdir()
    publish_artifact_set(target, _artifacts())
    assert not backup.exists()
