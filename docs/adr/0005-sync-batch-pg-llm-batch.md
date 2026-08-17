# ADR-0005: Standalone sync/batch routing with optional pg-llm-batch

## Status

`implemented_on_protected_main`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Interactive requests and bulk evaluation or embedding workloads have
different latency, throughput, and price characteristics. Chen et al. (2023)
show that LLM cost varies by orders of magnitude across models, so a gateway
should price requests and cascade to cheaper capable paths. Ong et al. (2024)
ground learned strong/weak routing toward a cost/quality target. Ding et al.
(2024) ground quality-aware routing of easier queries to a cheaper model
while keeping harder queries on a stronger path.

Those papers motivate **cost-aware selection** and **difficulty routing**.
They do not, by themselves, prove that this repository’s interactive-versus-
batch channel split is the same scientific claim. The sync/batch policy is a
product inference and needs its own evidence.

The orchestrator must keep one cost and policy boundary without making
standalone use depend on an external batch service. Optional
[`pg-llm-batch`](https://github.com/ContextualWisdomLab/pg-llm-batch)
integration is a sibling link, not a required control plane.

## Considered alternatives

- Sync only: simple but uneconomical for latency-tolerant work.
- Make `pg-llm-batch` mandatory: breaks standalone modularity.
- Duplicate cost policy in both services: creates contradictory evidence.
- Shared routing contract with local and injected backends: selected.

## Decision

`RoutingPolicy` uses explicit request hints
(`{"routing": {"latency_tolerant": true}}`) and KV thresholds. Interactive
work stays on sync execution. Latency-tolerant work uses a `BatchBackend` or
embedding backend. Local in-process implementations preserve
offline/standalone behavior. Injected `pg-llm-batch` adapters preserve
external ownership.

Bulk embedding work (for example naruon email-import backfill) submits to
`POST /v1/batch/embeddings` and records one usage-ledger row per original
vector. That naruon call is composition, not an MSA violation; see
[ADR-0012](0012-standalone-and-cwl-boundary.md).

Missing provider usage is labeled, not invented. A path that bypasses the
evidence writer is not treated as zero cost.

## Consequences

Callers receive observable job states. External adapters add operational
dependencies but do not remove the interactive path. Cost comparison can use
one attribution vocabulary only for the coordinator paths that record usage.

## Failure and recovery

Submit, poll, and retrieve failures remain non-success job states. Oversized
embedding inputs split under explicit limits. External outage does not convert
a job to complete or prevent local interactive requests.

## Security, privacy, and governance impact

The external backend receives only its versioned payload and purpose metadata
(National Institute of Standards and Technology, 2024a). It owns transport,
authorization, persistence, retention, and job tenancy under its contract; the
orchestrator cannot infer those controls.

## Compatibility and migration

The local backend is the default. Adopting `pg-llm-batch` injects adapters and
config rather than changing caller schema. Backend identifiers and result
semantics remain stable. The shared naruon fixture
`tests/fixtures/batch_embeddings_contract.json` is a contract, not a hidden
repository merge.

## Verification and acceptance

Tests cover decision reasons, sync and batch use, submit/poll/retrieve,
embeddings splitting and reduction, attribution, malformed or partial results,
and the naruon-shaped batch document.

## Rollback and supersession

Route affected work to the local backend or disable latency-tolerant
submission. Supersede only with an adapter that preserves job, evidence, and
standalone contracts.

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*
(arXiv:2305.05176) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* (arXiv:2406.18665, Version 4) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2406.18665

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM: Cost-efficient
and quality-aware query routing* (arXiv:2404.14618) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2404.14618

National Institute of Standards and Technology. (2024a). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

See also [docs/papers/README.md](../papers/README.md) and
[docs/REFERENCES.md](../REFERENCES.md).
