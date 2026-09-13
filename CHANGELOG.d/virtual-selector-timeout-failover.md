Fixed passthrough requests made through a virtual model selector (the
default model, `orchestrator/auto`, or `orchestrator/free`) failing the
entire request closed after a single candidate's ambiguous transport
failure (a read/connect timeout, reset, or truncated connection), even when
other ready, eligible candidates existed in the pool. Noema review's
`orchestrator/free` calls hit this in production (noema-review run 34754423834
attempt 2, PR #1166): one candidate's 90s read timeout returned
`502 provider_connection_error` while three other ready free-pool candidates
were never called. `TaskOrchestrator.proxy_completion`'s candidate loop now
distinguishes the two cases the ambiguous-transport-failure rule (#1045)
always conflated: an explicit concrete model the caller pinned still fails
closed without replay (nothing is safe to substitute it with), while a
virtual selector — where the caller delegated candidate selection to the
gateway — now advances to the next ranked, provider-diverse candidate, the
same way it already does for a rejected 429/5xx or a stale model response.
The failed candidate is still recorded as a breaker observation either way,
and exhausting every candidate still raises the same classified
`502 provider_connection_error` as before.
