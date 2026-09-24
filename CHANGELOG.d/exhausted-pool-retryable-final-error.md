### Exhausted pools no longer report a transient outage as a caller error

- When every `orchestrator/free` candidate fails, `_invoke` used to surface whichever classified upstream error came last. A pool that timed out on two providers and got a 400 from the third answered `400 invalid_request_error` (non-retryable). The same outcomes in another order answered `504 provider_timeout`.
- Noema evidence (sanitized sidecar logs, 2026-09-16..21): 10 review requests ended in 400. In 5 of them, earlier candidates had failed transiently (for example 8 transient failures out of 9 attempts). A caller treats 400 as a permanent request fault and skips its bounded capacity re-dispatch.
- The final retryability classification is now order-independent. A non-retryable last failure no longer hides an earlier retryable one, and a pool where every candidate rejected the request still reports 400. The exact status among different retryable failures still follows the last such failure. Retry/replay authorization, the circuit breaker and 413/429 handling are unchanged.
- Regression: `tests/test_exhausted_pool_final_error_order.py`.
