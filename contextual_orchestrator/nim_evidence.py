"""Validate and atomically publish evidence from optional NIM benchmarks.

This module deliberately contains no scoring, routing, vector, uncertainty, or
Pareto arithmetic.  It is the small trust boundary shared by future benchmark
adapters: immutable task identity in, complete provenance-bearing artifacts out.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

try:  # pragma: no cover - selected by the host platform
    import fcntl
except ImportError:  # pragma: no cover - Windows compatibility
    fcntl = None  # type: ignore[assignment]
    import msvcrt

NIM_EVIDENCE_SCHEMA_VERSION = "1.0.0"
NIM_ARTIFACT_NAMES = frozenset(
    {
        "benchmark_report.json",
        "benchmark_cells.csv",
        "benchmark_summary.md",
        "run_provenance.json",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROVENANCE_FIELDS = (
    "source_commit",
    "catalog_snapshot_sha256",
    "task_manifest_sha256",
    "pricing_scenario_sha256",
    "workflow_run_id",
    "evidence_status",
)


class NimEvidenceError(ValueError):
    """Raised when benchmark evidence is malformed or cannot be published safely."""


def canonical_json_sha256(value: object) -> str:
    """Return the SHA-256 of deterministic UTF-8 JSON without doing model arithmetic."""
    import hashlib

    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_task_manifest(manifest: object) -> dict[str, object]:
    """Return a validated manifest with unique immutable task/scorer identities."""
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != NIM_EVIDENCE_SCHEMA_VERSION
    ):
        raise NimEvidenceError(
            f"task manifest schema_version must be {NIM_EVIDENCE_SCHEMA_VERSION}"
        )
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise NimEvidenceError("task manifest requires a non-empty tasks list")
    task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise NimEvidenceError("each task must be an object")
        task_id = task.get("task_id")
        prompt = task.get("prompt")
        scorer = task.get("scorer")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise NimEvidenceError("task_id must be a unique non-empty string")
        if not isinstance(prompt, str) or not prompt:
            raise NimEvidenceError(f"task {task_id} requires a non-empty prompt")
        if not isinstance(scorer, dict):
            raise NimEvidenceError(f"task {task_id} requires a scorer object")
        identity = (scorer.get("name"), scorer.get("version"))
        if not all(isinstance(item, str) and item for item in identity):
            raise NimEvidenceError(f"task {task_id} requires scorer name and version")
        task_ids.add(task_id)
    return manifest


def validate_provenance(provenance: object) -> dict[str, str]:
    """Return complete, secret-free provenance or fail closed before publication."""
    if not isinstance(provenance, dict) or set(provenance) != set(_PROVENANCE_FIELDS):
        raise NimEvidenceError("provenance fields are incomplete or unexpected")
    normalized: dict[str, str] = {}
    for field in _PROVENANCE_FIELDS:
        value = provenance[field]
        if not isinstance(value, str) or not value:
            raise NimEvidenceError(f"provenance {field} must be a non-empty string")
        if (
            field == "source_commit"
            and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None
        ):
            raise NimEvidenceError("provenance source_commit must be a Git object ID")
        if (
            field.endswith("_sha256")
            and not (field == "pricing_scenario_sha256" and value == "unknown")
            and _SHA256.fullmatch(value) is None
        ):
            raise NimEvidenceError(f"provenance {field} must be a lowercase SHA-256")
        normalized[field] = value
    return normalized


def _residue(final: Path, kind: str) -> list[Path]:
    """Return private publication residue for one final directory."""
    prefix = f".{final.name}.{kind}-"
    return sorted(path for path in final.parent.iterdir() if path.name.startswith(prefix))


@contextmanager
def _publication_lock(final: Path) -> Iterator[None]:
    """Serialize publishers that target the same evidence directory."""
    lock_path = final.parent / f".{final.name}.publish-lock"
    if lock_path.is_symlink():
        raise NimEvidenceError("publication lock must not be a symbolic link")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise NimEvidenceError("publication lock could not be opened safely") from exc
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows compatibility
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        else:  # pragma: no cover - Windows compatibility
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


def _remove_staging(path: Path) -> None:
    """Remove private staging even when a crash preserved a read-only mode."""
    try:
        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IRWXU)
        shutil.rmtree(path)
    except OSError as exc:
        raise NimEvidenceError("abandoned publication staging requires operator review") from exc


def _recover_publication(final: Path) -> None:
    """Remove abandoned staging and restore one unambiguous crash backup."""
    for staging in _residue(final, "staging"):
        _remove_staging(staging)
    backups = _residue(final, "backup")
    if len(backups) > 1:
        raise NimEvidenceError("multiple publication backups require operator review")
    if backups:
        if final.exists():
            try:
                _remove_staging(backups[0])
            except NimEvidenceError:
                pass
        else:
            os.replace(backups[0], final)


def publish_artifact_set(
    output_directory: str | os.PathLike[str], artifacts: Mapping[str, bytes]
) -> None:
    """Publish exactly one complete artifact set, restoring the prior set on failure."""
    if set(artifacts) != NIM_ARTIFACT_NAMES or any(
        not isinstance(value, bytes) or not value for value in artifacts.values()
    ):
        raise NimEvidenceError(
            "artifact set must contain exactly four non-empty byte payloads"
        )
    try:
        provenance = json.loads(artifacts["run_provenance.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NimEvidenceError("run_provenance.json must contain valid UTF-8 JSON") from exc
    validate_provenance(provenance)

    final = Path(output_directory).expanduser()
    if final.name in {"", ".", ".."}:
        raise NimEvidenceError("output directory must name a dedicated directory")
    final = final.parent.resolve() / final.name
    if final.is_symlink() or (final.exists() and not final.is_dir()):
        raise NimEvidenceError("output directory must be a real directory")
    final.parent.mkdir(parents=True, exist_ok=True)
    with _publication_lock(final):
        _recover_publication(final)
        staging = final.parent / f".{final.name}.staging-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o777)
        final_mode = stat.S_IMODE(final.stat().st_mode) if final.exists() else None
        backup: Path | None = None
        try:
            for name, payload in artifacts.items():
                (staging / name).write_bytes(payload)
            if final_mode is not None:
                staging.chmod(final_mode)
            if final.exists():
                backup = final.parent / f".{final.name}.backup-{uuid.uuid4().hex}"
                os.replace(final, backup)
            try:
                os.replace(staging, final)
            except BaseException:
                if backup is not None and backup.exists():
                    os.replace(backup, final)
                raise
            if backup is not None:
                try:
                    _remove_staging(backup)
                except NimEvidenceError:
                    pass
        finally:
            if staging.exists():
                _remove_staging(staging)
