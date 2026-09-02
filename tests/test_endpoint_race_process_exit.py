"""Regression: an uncancellable losing race participant must not block exit."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path


def test_uncancellable_loser_never_returning_does_not_block_process_exit() -> None:
    """A losing race attempt stuck in an unbounded call must not join at shutdown.

    Regression for a Devin Review finding ("Endpoint races block process
    shutdown", ContextualWisdomLab/contextual-orchestrator#971): with this
    org's default no-deadline ``ModelClient.timeout=None`` policy,
    ``race_first_valid`` used to fan its attempts out across a
    ``concurrent.futures.ThreadPoolExecutor``. That executor's worker
    threads register with ``concurrent.futures.thread``'s own
    interpreter-exit hook, which unconditionally *joins* every
    still-running worker at shutdown regardless of that worker's own
    daemon status. A losing attempt whose equivalence contract does not
    support cancellation (``cancellation_supported=False``, the
    ``cancel_loser`` "safe_drain" path) and whose blocking call never
    returns would therefore hang the whole process at exit, forever, even
    though the winner already answered the caller and ``race_first_valid``
    already returned. ``race_first_valid`` now drives each attempt from a
    plain ``threading.Thread(daemon=True)`` -- never a
    ``ThreadPoolExecutor`` -- so an abandoned loser carries no such
    registration and the process can still exit.

    Verified end-to-end in a real, separate interpreter (an in-process
    thread-introspection assertion cannot distinguish "still hanging in
    the background" from "would actually block this process's shutdown"
    -- the whole point of the finding): a helper script calls
    ``race_first_valid`` with one attempt that blocks on an ``Event`` that
    is never set and one that returns immediately, then -- after
    ``race_first_valid`` has already returned the winner -- lets the
    script's ``__main__`` fall through to a normal, unforced exit with no
    explicit ``sys.exit()``/``os._exit()``. RED-before/GREEN-after against
    the pre-fix ``ThreadPoolExecutor`` version: the same script hung for
    the full outer bound and was killed; it exits cleanly, well under that
    bound, with this fix.
    """
    script = textwrap.dedent(
        """
        import sys
        import threading

        sys.path.insert(0, %(repo_root)r)
        from contextual_orchestrator.endpoint_race import (
            EndpointAttempt,
            EndpointEquivalenceContract,
            race_first_valid,
        )

        never_set = threading.Event()

        def hung_loser():
            never_set.wait()  # Hangs forever -- nothing ever sets this event.
            raise AssertionError("unreachable: the stalled loser must never return")

        def fast_winner():
            return "winner"

        contract = EndpointEquivalenceContract(
            contract_id="process_exit_regression",
            model_revision="revision_2026_09",
            reasoning_effort_profile="worker_medium",
            capability_set=("text",),
            structured_output_contract="openai_response_v1",
            accuracy_class="full_precision",
            data_residency_policy="kr_region_only",
            retention_policy="zero_retention",
            context_limit=128_000,
            pricing_evidence_id="catalog_snapshot_2026_09_02",
            hedge_eligible=True,
            cancellation_supported=False,
            execution_policy="immediate_race",
        )

        outcome = race_first_valid(
            [
                EndpointAttempt("stuck_endpoint", contract, hung_loser),
                EndpointAttempt("fast_endpoint", contract, fast_winner),
            ],
            validate=bool,
            deadline_seconds=None,
            max_concurrency=2,
        )
        assert outcome.value == "winner"
        assert outcome.cancellation_outcomes == (("stuck_endpoint", "safe_drain"),)
        # No explicit sys.exit()/os._exit(): a genuinely non-blocking fix
        # must let normal interpreter shutdown proceed on its own, with the
        # hung loser thread still blocked in the background.
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
    assert elapsed < 5.0, f"process took {elapsed:.1f}s to exit with an uncancellable loser outstanding"
