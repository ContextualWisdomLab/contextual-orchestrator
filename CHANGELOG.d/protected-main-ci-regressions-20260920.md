## Fixed

- Protected-main CI now installs rustfmt and clippy for the repository-pinned Rust
  1.97.1 toolchain, follows the renamed provider embedding claim-lease constant,
  and locks anyio 4.14.2 to remove CVE-2026-63374, CVE-2026-64847, and
  CVE-2026-63349.
- Provider embedding synchronous completion now treats an explicit null wait
  timeout as unbounded, matching the default-null model timeout contract.
- The embedding shutdown regression now closes its test-owned HTTP listener
  after joining the serving thread, eliminating the strict ResourceWarning.
- Restores the availability-only `OpenRouterUptimeCollector` that the restack merge `3078949c` dropped by taking main's side of `openrouter_uptime.py` and `orchestrator.py` wholesale while keeping the branch's tests. The collector again folds uptime only into the transport ledger and never takes the answer-quality router (branch commit `b3be48e3`), and it keeps main's independent `_UPTIME_FETCH_TIMEOUT_SECONDS` bound. `tests/test_openrouter_uptime.py` goes from 77 failures to 79 passed.
- `OpenRouterUptimeCollector.stop()` now takes the same commit lock as the poll's stop re-check and evidence write, so no transport-prior update can land after `stop()` returns (CodeRabbit discussion_r4065984128); the uptime fetch stays outside the lock.
