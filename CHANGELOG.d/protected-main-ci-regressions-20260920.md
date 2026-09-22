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
- The whole-request partitioning planning ADR now carries identifier `0135` (`docs/planning/adrs/0135-whole-request-partitioning.md`, the same number and content open PR #1088 assigns), so the date-prefixed filename no longer reads as ADR `2026` without an identifier.
- The paper inventory now lists arXiv 2512.24601 (verified against the arXiv abstract page and API) and the four timeout-allocator DOIs 10.1002/0471722162, 10.1080/00031305.1996.10473566, 10.1080/01621459.1958.10501452 and 10.2307/2530286 (verified against Crossref metadata), so the paper-discovery contract tests pass.
- A virtual-selector route whose every candidate returns 429 without `Retry-After` now always ends as the honest storm `429 provider_rate_limited` (`cooldown_source: assumed`, terminal reason `rate_limit_wait_budget_exhausted`) once the wait budget is spent, per `_await_rate_limit_recovery`'s contract; a pinned concrete model keeps the raw `rate_limit_exceeded`. Previously a candidate that `_invoke` skipped while its assumed cooldown was still running, and that became ready moments later, was read by `_invoke_with_rate_limit_recovery` as a mixed failure, so real call latency made the request fail early with the raw 429 without retrying the ready candidate (the flaky `test_invoke_preserves_final_classified_failure_across_candidates`). Selection now re-runs within the budget for such a candidate; a candidate that was attempted, or failed for a non-rate-limit reason, still re-raises immediately. The regression is now deterministic (simulated clock, per-call cost 0 and 10 ms).
