# Provider embedding shutdown and durable wait

PR #1249 review at `bb1fae3dd997b9f3bf60d5ab486ca45ede20c595` exposed two lifecycle failures. Shutdown could run after the worker checked its closed state but before the durable terminal commit, allowing a late success or failure to survive shutdown. A separate process could cancel a durable job while the local caller waited indefinitely on a process-local event.

Reuse the backend's existing executor lock for the closed-state transition and terminal publication. Publication that wins first completes before shutdown becomes visible; shutdown that wins first marks the execution claim lost and leaves recoverable durable work without late results, usage, or failure. The worker pool shuts down outside the lock. Existing durable claim and cancellation transactions remain authoritative.

For durable waits with no finite caller deadline, observe shared terminal state at the existing claim-renewal cadence. This is an observation interval, never an execution deadline or a provider failure verdict. Finite caller waits retain their existing behavior; local events still wake shutdown waiters.

## Verification

Observed 2026-09-27. Five regression cases cover both terminal outcome races, publication winning before close, and remote cancellation with `None` and infinite caller deadlines. The four shutdown-wins/cancellation cases fail on the unchanged review head; the race cases persist late terminal data and cancellation waiters remain blocked. Related batch registry, provider backend, and batch-routing suites pass: 74 tests. The baseline environment also emits the existing pytest unknown `asyncio_default_fixture_loop_scope` configuration warning; it is not suppressed or claimed resolved.

```sh
.venv/bin/python -m pytest tests/test_batch_job_registry.py tests/test_provider_embedding_batch_backend.py tests/test_batch_routing.py -q
```

These local tests do not establish current-head hosted checks or independent Noema/OpenCode approval.

## Canonical integration preservation, 2026-09-27

The #1266 integration at `515ee5beb68cc5ba892f99842e073fbae0e166ef`
was missing both the earlier shutdown/claim-renewal ownership repair and the
newer atomic publication/durable-wait repair. Comparing the three runtime and
test files with #1249 head `8e9999ce34e11b39a4efa0c34b0a1c3811663707`
showed only the missing ownership and observation deltas; no independent
canonical registry behavior was removed.

Reusing the four shutdown-wins/remote-cancellation regressions against unchanged
#1266 runtime produced 4 failures (session 2172, exit 1). Both late terminal
outcomes persisted, and both unbounded waiters stayed blocked after remote
cancellation. Carrying the existing owner implementation and all its regression
cases restores the claim-renewal stop, close wakeup, atomic shutdown fence and
shared terminal observation together. The registry, provider backend, batch
routing and default embedding-wait suites pass with warnings as errors:
75 tests, session 53729, exit 0. This remains local integration evidence;
current-head hosted checks and independent review are required.
