"""Regression coverage for daemon worker pool shutdown ordering."""

from __future__ import annotations

import pytest

from contextual_orchestrator.batch_routing import _DaemonWorkerPool


def test_daemon_worker_pool_rejects_submit_after_shutdown() -> None:
    """Shutdown must close admission before worker sentinels are queued."""
    pool = _DaemonWorkerPool(max_workers=1)
    pool.shutdown(wait=False, cancel_futures=True)

    with pytest.raises(RuntimeError, match="shutdown"):
        pool.submit(lambda: None)
