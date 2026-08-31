# ADR 0005: Provider-embedding lease and token-accounting boundary

- Status: Accepted
- Date: 2026-08-31
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not a planning-ADR number.

## Context

Provider embedding jobs may outlive one Valkey execution-claim lease. A
worker whose renewal fails can no longer prove that it owns the job, while a
different worker may acquire the same claim. Publishing the first worker's
result after that point would make usage, result, and terminal state depend
on an expired lease.

The embedding subsystem also builds a PyO3 extension backed by
`tiktoken-rs`, but the Python runtime did not call it. Its historical local
fallback estimated tokens from word units. Such an estimate cannot enforce a
provider token limit or support billed cost accounting. OpenAI's published
`tiktoken` mapping declares `cl100k_base` for
`text-embedding-ada-002`, `text-embedding-3-small`, and
`text-embedding-3-large`; it does not authorize guessing a tokenizer for an
unknown model identifier.

Redis's distributed-lock guidance requires a client to act only while it
still owns the lock and recommends fencing when correctness depends on
exclusive work. PyO3's module interface supports an in-package extension, so
the existing Rust library can be loaded without adding a provider SDK or a
second tokenization implementation.

Chubby's production experience likewise separates coarse-grained advisory
locking from the application-specific checks needed before publishing state;
that operational boundary grounds the explicit terminal-publication fence here.

## Decision

1. **Lease loss is observable.** A durable execution claim exposes an
   ownership check. A failed renewal, an elapsed renewal deadline, an
   ownership-check error, or a negative ownership result marks the claim
   lost and fails closed.
2. **Terminal publication is fenced and atomic.** One Valkey Lua transaction
   verifies the execution-claim token, accepts only `queued` or `running`, and
   writes result/usage/error plus the terminal state together. The same fence
   protects success and failure. A stale worker leaves recoverable `running`
   state and retries claim acquisition while the backend remains live; it does
   not overwrite a successor or require a process restart.
3. **The provider call is not declared exactly-once.** A synchronous
   provider call cannot be cancelled retroactively when its lease is lost.
   Duplicate upstream execution remains possible during a partition. This
   decision fences stale local publication; provider-side idempotency needs a
   separate supported contract.
4. **Embedding counts are authoritative or unavailable.** An explicitly
   configured `pg_tiktoken` counter remains first. Otherwise the packaged
   Rust counter is used only for the three published cl100k embedding model
   identifiers above. Missing or failing native code and an unknown tokenizer
   produce an explicit unavailable outcome. Embedding splitting, provider
   dispatch, usage publication, and cost publication do not substitute a
   word-count or BPE heuristic.
5. **No routing/model inference is added.** The mapping is an exact tokenizer
   contract, not evidence for model quality, provider selection, or
   equivalence. The native extension does not count chat framing.
6. **Legacy chat estimation remains a known gap.** This ADR makes no global
   token-accounting compliance claim. Existing chat routing and missing-usage
   cost paths still use `HeuristicTokenCounter`; replacing that estimate with
   authoritative provider/tokenizer evidence is required follow-up work.

## Consequences

### Positive

- An expired worker cannot publish a terminal provider-embedding result.
- Installed production wheels execute the existing Rust cl100k counter.
- Missing tokenizer authority is visible before provider dispatch and before
  a cost record can be fabricated.
- The PostgreSQL tokenizer boundary and dependency-injected test seams remain
  available.

### Negative

- Embedding requests for an undeclared tokenizer reject unless an
  authoritative PostgreSQL counter is configured.
- Lease fencing prevents stale publication but does not eliminate duplicate
  provider work.
- Chat estimates remain outside this narrow compliance boundary.

## References

Burrows, M. (2006). *The Chubby lock service for loosely-coupled distributed
systems*. 7th USENIX Symposium on Operating Systems Design and Implementation.
https://research.google/pubs/the-chubby-lock-service-for-loosely-coupled-distributed-systems/

The publisher-hosted paper is linked rather than copied because repository
redistribution permission was not established.

Redis Ltd. (n.d.). *Distributed locks with Redis*.
https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/

PyO3 Project. (n.d.). *Python modules*.
https://pyo3.rs/main/module

OpenAI. (n.d.). *OpenAI public encodings*.
https://github.com/openai/tiktoken/blob/main/tiktoken_ext/openai_public.py

ContextualWisdomLab. (2026). *Cost-aware sync-versus-batch routing*
(ADR 0003).
https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/main/docs/adr/0003-cost-aware-sync-batch-routing.md
