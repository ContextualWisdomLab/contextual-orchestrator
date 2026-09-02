"""Repair the batch-worker usage fixture after transport-provenance hardening."""

from __future__ import annotations

from pathlib import Path


TARGET = Path("tests/test_batch_optimizer.py")
OLD = '''def test_batch_route_persists_runs_with_usage() -> None:\n    client = _CountingClient()\n    orchestrator = _orch(client)\n    records = orchestrator.batch_route([t["prompt"] for t in TASKS])\n\n    assert len(records) == 3\n'''
NEW = '''def test_batch_route_persists_runs_with_usage() -> None:\n    client = _CountingClient()\n    orchestrator = _orch(client)\n    # This regression measures the worker Batch API usage contract only.  The\n    # full CI environment installs fast-mlsirm, whose optional model-judge call\n    # is a separate spend source; allowing it into this fixture would make the\n    # aggregate usage source correctly mixed/unavailable and stop testing the\n    # worker provenance this case is named for.\n    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=None):\n        records = orchestrator.batch_route([t["prompt"] for t in TASKS])\n\n    assert len(records) == 3\n'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one worker-usage fixture target, found {count}")
    TARGET.write_text(text.replace(OLD, NEW), encoding="utf-8")


if __name__ == "__main__":
    main()
