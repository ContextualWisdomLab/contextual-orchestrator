# Provider catalog overlay + capability-first known-cost routing

- Discover models for the five org credential names after KV registration.
- Fail-closed refresh: last-known-good kept; no invented workers; 429/5xx/timeout contained.
- Bytez catalog is native `/models/v2`, not OpenAI-shaped.
- Route selection: capability first, known price second (PR #575). Unpriced is not free.
- Served-free with a known list/original price competes at that list price, not as cost 0.0.
- Explicit $0 with no list price remains a known price of 0. Missing/non-finite stay unpriced.
- Failover remains post-error resilience. Issue #86 quality/Pareto is out of this slice.
