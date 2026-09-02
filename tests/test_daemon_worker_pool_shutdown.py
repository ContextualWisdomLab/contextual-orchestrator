"""Regression coverage for daemon worker pool shutdown ordering."""

from __future__ import annotations

import queue
import threading

import pytest

from contextual_orchestrator.batch_routing import _DaemonWorkerPool


def test_daemon_worker_pool_rejects_submit_after_shutdown() -> None:
    """Shutdown must close admission before worker sentinels are queued."""
    pool = _DaemonWorkerPool(max_workers=1)
    pool.shutdown(wait=False, cancel_futures=True)

    with pytest.raises(RuntimeError, match="shutdown"):
        pool.submit(lambda: None)


def test_daemon_worker_pool_shutdown_is_idempotent() -> None:
    """A second ``shutdown()`` call must not error or re-cancel/re-queue.

    Regression for ContextualWisdomLab/contextual-orchestrator#971: the
    admission flag now gates the drain and sentinel steps, so repeating
    ``shutdown()`` after it already ran must be a harmless no-op beyond the
    (already-terminated) worker join.
    """
    pool = _DaemonWorkerPool(max_workers=1)
    pool.submit(lambda: None)

    pool.shutdown(wait=True, cancel_futures=True)
    # Must not raise, hang, or attempt to cancel/queue anything a second
    # time -- the pool is already fully torn down.
    pool.shutdown(wait=True, cancel_futures=True)


def test_daemon_worker_pool_submit_racing_shutdown_cannot_execute() -> None:
    """A ``submit()`` that races ``shutdown(cancel_futures=True)`` must lose.

    Regression for the Devin finding "Concurrent shutdown admits cancelled
    work" (ContextualWisdomLab/contextual-orchestrator#971): before the fix,
    ``shutdown()`` drained the queue *before* closing admission, so a
    ``submit()`` landing in that gap could enqueue work that survived the
    cancellation drain and later ran on a worker despite
    ``cancel_futures=True``.

    This test forces that exact interleaving deterministically -- no real
    thread-timing luck involved -- by hooking the queue drain's empty-check
    (the point where the old code was about to leave the vulnerable window)
    and holding it open with an ``Event`` until a concurrent ``submit()``
    has had a chance to run. Under the fix, admission is already closed by
    the time the drain even starts, so the racing ``submit()`` must observe
    the closed pool and raise instead of enqueuing -- and its work must
    never execute.
    """
    pool = _DaemonWorkerPool(max_workers=1)

    drain_found_empty = threading.Event()
    release_submit = threading.Event()
    executed = threading.Event()
    original_get_nowait = pool._queue.get_nowait

    def instrumented_get_nowait() -> object:
        try:
            return original_get_nowait()
        except queue.Empty:
            # The drain has just found the queue empty and is about to
            # return control to ``shutdown()`` -- exactly the window the
            # unfixed implementation left open before closing admission.
            # Hold it open long enough for the racing submit() below to run.
            drain_found_empty.set()
            release_submit.wait(timeout=5.0)
            raise

    pool._queue.get_nowait = instrumented_get_nowait

    submit_errors: list[BaseException] = []

    def racing_submit() -> None:
        assert drain_found_empty.wait(timeout=5.0), "drain never reached the empty check"
        try:
            pool.submit(executed.set)
        except BaseException as exc:  # noqa: BLE001 - captured for assertion below
            submit_errors.append(exc)
        finally:
            release_submit.set()

    racer = threading.Thread(target=racing_submit)
    racer.start()
    try:
        pool.shutdown(wait=True, cancel_futures=True)
    finally:
        racer.join(timeout=5.0)

    assert not racer.is_alive(), "racing submit() thread never completed"
    assert len(submit_errors) == 1, "racing submit() must observe the closed pool"
    assert isinstance(submit_errors[0], RuntimeError)
    assert not executed.is_set(), "cancelled work must never execute"
