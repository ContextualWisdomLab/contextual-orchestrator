"""Regression: an unbounded provider embedding runner must not block exit."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path


def test_hung_provider_embedding_runner_does_not_block_process_exit_after_close() -> None:
    """A never-returning embedding runner must not block interpreter shutdown.

    Regression for a Devin Review finding ("Unbounded embeddings block
    process shutdown", ContextualWisdomLab/contextual-orchestrator#971):
    ``ProviderEmbeddingBatchBackend`` used to fan its durable, pollable job
    queue out across a ``concurrent.futures.ThreadPoolExecutor``. That
    executor's worker threads register with ``concurrent.futures.thread``'s
    own interpreter-exit hook, which unconditionally *joins* every
    still-running worker at shutdown regardless of that worker's own daemon
    status. ``cost_router.py``'s ``_provider_embedding_backend`` passes
    ``execution_timeout_seconds=None`` by default (this org's deliberate
    no-deadline ``ModelClient.timeout=None`` policy), and even a finite
    timeout there is only a *cooperative* check performed after the
    runner call returns -- never a preemptive cancellation of an in-flight
    call. A worker permanently blocked inside a provider embedding runner
    that never returns would therefore hang the join, and therefore process
    shutdown, forever -- even after ``ProviderEmbeddingBatchBackend.close()``
    had already been called. ``ProviderEmbeddingBatchBackend`` now drives its
    bounded worker pool from a private ``_DaemonWorkerPool`` built on plain
    ``threading.Thread(daemon=True)`` workers, never
    ``ThreadPoolExecutor``, so an abandoned worker carries no such
    registration and the process can still exit.

    Verified end-to-end in a real, separate interpreter (an in-process
    thread-introspection assertion cannot distinguish "still hanging in the
    background" from "would actually block this process's shutdown" -- the
    whole point of the finding): a helper script submits one embedding job
    whose runner blocks on an ``Event`` that is never set, waits for the job
    to actually reach the "running" state (so the runner is genuinely
    in-flight, not merely queued), calls ``backend.close()`` -- mirroring a
    real server shutdown -- and then lets the script's ``__main__`` fall
    through to a normal, unforced exit with no explicit
    ``sys.exit()``/``os._exit()``. RED-before/GREEN-after against the
    pre-fix ``ThreadPoolExecutor`` version: the same script hung for the
    full outer bound and was killed; it exits cleanly, well under that
    bound, with this fix.
    """
    script = textwrap.dedent(
        """
        import sys
        import threading
        import time

        sys.path.insert(0, %(repo_root)r)
        from contextual_orchestrator.batch_routing import (
            EmbeddingBatchRequest,
            ProviderEmbeddingBatchBackend,
        )

        never_set = threading.Event()
        runner_entered = threading.Event()

        def hung_runner(requests):
            runner_entered.set()
            never_set.wait()  # Hangs forever -- nothing ever sets this event.
            raise AssertionError("unreachable: the stalled runner must never return")

        backend = ProviderEmbeddingBatchBackend(hung_runner, max_concurrency=1)
        job = backend.submit(
            [EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")]
        )
        assert runner_entered.wait(timeout=5), "runner never started"
        # The runner is now genuinely blocked inside the worker thread --
        # not merely queued -- exactly the scenario the finding describes.
        deadline = time.monotonic() + 2
        while backend.poll(job)["status"] != "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert backend.poll(job)["status"] == "running"

        backend.close()
        assert backend.poll(job)["status"] == "running"
        # No explicit sys.exit()/os._exit(): a genuinely non-blocking fix
        # must let normal interpreter shutdown proceed on its own, with the
        # hung runner thread still blocked in the background.
        """
    ) % {"repo_root": str(Path(__file__).resolve().parents[1])}

    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stderr
    assert elapsed < 5.0, f"process took {elapsed:.1f}s to exit with a hung embedding runner outstanding"
