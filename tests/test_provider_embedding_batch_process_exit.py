"""Process-exit regression coverage for provider embedding batch workers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap


def test_blocked_provider_embedding_worker_does_not_hold_interpreter_exit() -> None:
    """A no-deadline provider call must not keep the Python process alive."""
    repository_root = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(
        """
        import threading

        from contextual_orchestrator.batch_routing import (
            EmbeddingBatchRequest,
            ProviderEmbeddingBatchBackend,
        )

        started = threading.Event()
        release = threading.Event()

        def blocked_runner(_requests):
            started.set()
            release.wait()
            return [[0.0]], 1

        backend = ProviderEmbeddingBatchBackend(
            blocked_runner,
            max_concurrency=1,
            execution_timeout_seconds=None,
        )
        backend.submit([EmbeddingBatchRequest(input_text="blocked")])
        if not started.wait(timeout=2.0):
            raise SystemExit("provider worker did not start")
        backend.close()
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )

    assert completed.returncode == 0, completed.stderr
