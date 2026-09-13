Under a provider 429 storm (org CI review lanes hit this on `orchestrator/free`:
noema run 34758641142, strix run 34758679736 -- every candidate returned 429
within ~50ms; see `ContextualWisdomLab/.github#2148`, `#2165`), the gateway no
longer fails the request immediately. It now parses `Retry-After` (delta-seconds
or an HTTP-date) and, when absent, a numeric `x-ratelimit-reset*` header, tracks
a per-agent quota cooldown separate from the health circuit breaker (a 429 is
quota exhaustion, not a model health failure, and no longer trips the breaker),
skips a currently cooled-down candidate by default in `_failover_candidates`
(shared by every caller), and waits out the earliest cooldown -- one shared
`_await_rate_limit_recovery` implementation -- when it fits the request's
administrator-owned model deadline (issue #1053) or the new
`rate_limit_wait_seconds` caller-contract default (30s), retrying once the
wait elapses. Both real request paths reach it: `proxy_completion`'s
passthrough failover loop, and `route_once`/`conduct` (every step, including
the worker step) via `_invoke_with_rate_limit_recovery`, which is what
`orchestrator/free` actually runs over `/v1/chat/completions`. When waiting is
impossible, the gateway now returns an honest `429` with error code
`provider_rate_limited` and a `Retry-After` header (or the equivalent terminal
SSE error frame when streaming) instead of misclassifying quota exhaustion as
a `502` connection failure. `provider_readiness_report`
(`/api/v1/provider_readiness/latest`) now also reports `rate_limited_until` and
`earliest_ready_seconds` so an external preflight/readiness sidecar can wait
instead of exiting.

A 429 that states no cooldown at all (RFC 9110 permits omitting
`Retry-After`/`x-ratelimit-reset*`, and NIM/OpenRouter routinely do) now
records an assumed cooldown -- the new `rate_limit_unknown_cooldown_seconds`
default (5s) -- instead of nothing, so an all-omitted-header storm can no
longer look identical to "nothing is rate-limited" and fail as if this
feature did not exist; every cooldown surface labels itself
`cooldown_source: "provider"` or `"assumed"` accordingly, and a provider-stated
cooldown is never shortened or relabeled by a later assumed one. This
assumption applies to 429 only (a 503 with no header keeps requiring a real
provider-stated duration) and only across two or more candidates (a single
pinned/named candidate keeps its pre-existing immediate classified-error
contract unchanged) -- both scoped narrowly after concrete pre-existing-test
regression evidence, not by design intent alone.
