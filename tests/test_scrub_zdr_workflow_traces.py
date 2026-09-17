"""Smoke test for scripts/scrub_zdr_workflow_traces.py's dry-run/apply behavior."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scrub_zdr_workflow_traces import main  # noqa: E402


def _seed_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE orchestration_records (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "kind TEXT NOT NULL, key TEXT, payload TEXT NOT NULL)"
    )
    dirty_run = {
        "workflow_run_id": "run_dirty",
        "prompt_text": "private prompt content",
        "answer": "private answer content",
        "cache_status": "bypass",
        "trace": [{"id": "s1", "output": "raw worker output"}],
    }
    clean_run = {
        "workflow_run_id": "run_clean",
        "prompt_text": "ordinary prompt",
        "answer": "ordinary answer",
        "cache_status": "miss",
        "trace": [{"id": "s1", "output": "ordinary output"}],
    }
    conn.execute(
        "INSERT INTO orchestration_records (kind, key, payload) VALUES ('workflow_run', 'run_dirty', ?)",
        (json.dumps(dirty_run),),
    )
    conn.execute(
        "INSERT INTO orchestration_records (kind, key, payload) VALUES ('workflow_run', 'run_clean', ?)",
        (json.dumps(clean_run),),
    )
    conn.commit()
    conn.close()


def test_dry_run_reports_without_writing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "state.sqlite3")
        _seed_db(db_path)

        exit_code = main([db_path, "--workflow-run-id", "run_dirty"])

        assert exit_code == 0
        conn = sqlite3.connect(db_path)
        payload = conn.execute(
            "SELECT payload FROM orchestration_records WHERE key = 'run_dirty'"
        ).fetchone()[0]
        conn.close()
        assert "private prompt content" in payload  # dry run must not write


def test_apply_scrubs_only_targeted_row() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "state.sqlite3")
        _seed_db(db_path)

        exit_code = main([db_path, "--workflow-run-id", "run_dirty", "--apply"])

        assert exit_code == 0
        conn = sqlite3.connect(db_path)
        dirty_payload = conn.execute(
            "SELECT payload FROM orchestration_records WHERE key = 'run_dirty'"
        ).fetchone()[0]
        clean_payload = conn.execute(
            "SELECT payload FROM orchestration_records WHERE key = 'run_clean'"
        ).fetchone()[0]
        conn.close()

        assert "private prompt content" not in dirty_payload
        assert "raw worker output" not in dirty_payload
        assert json.loads(dirty_payload)["prompt_text"]["zdr_redacted"] is True
        assert clean_payload == json.dumps(
            {
                "workflow_run_id": "run_clean",
                "prompt_text": "ordinary prompt",
                "answer": "ordinary answer",
                "cache_status": "miss",
                "trace": [{"id": "s1", "output": "ordinary output"}],
            }
        )


def test_bypass_cache_heuristic_finds_dirty_row_without_explicit_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "state.sqlite3")
        _seed_db(db_path)

        exit_code = main([db_path, "--bypass-cache-heuristic", "--apply"])

        assert exit_code == 0
        conn = sqlite3.connect(db_path)
        dirty_payload = conn.execute(
            "SELECT payload FROM orchestration_records WHERE key = 'run_dirty'"
        ).fetchone()[0]
        clean_payload = conn.execute(
            "SELECT payload FROM orchestration_records WHERE key = 'run_clean'"
        ).fetchone()[0]
        conn.close()

        assert "private prompt content" not in dirty_payload
        assert "ordinary prompt" in clean_payload  # cache_status == "miss", untouched


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
