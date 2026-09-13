Fixed passthrough requests made through the `orchestrator/free` virtual model
selector failing the entire request closed after a single candidate's
ambiguous transport failure (a read/connect timeout, reset, or truncated
connection), even when other ready, eligible free-pool candidates existed.
Noema review's `orchestrator/free` calls hit this in production
(noema-review run 34754423834 attempt 2, PR #1166): one candidate's 90s read
timeout returned an error while three other ready free-pool candidates were
never called. `TaskOrchestrator.proxy_completion`'s candidate loop now
distinguishes the case the ambiguous-transport-failure rule (#1045) always
conflated: an explicit concrete model, or a priced virtual selector (the
default model / `orchestrator/auto`), still fails closed without replay —
`#1053` raises the non-retryable `502 provider_outcome_unknown` for these,
since replaying an accepted request onto another candidate could double-bill
a priced provider. `orchestrator/free` is the sole exception: its candidates
are admitted solely on explicit zero-cost evidence, so a replay there can
never double-bill, and the request now advances to the next ranked,
provider-diverse free candidate instead. The failed candidate is still
recorded as a breaker observation either way, and exhausting every
`orchestrator/free` candidate still raises the same non-retryable
`502 provider_outcome_unknown` for the last one tried. Advancing a priced
virtual selector across an ambiguous timeout would need its own ADR and is
deliberately not done here.
