# ADR-0005: Standalone sync/batch routing with optional pg-llm-batch

## Status

`implemented_on_protected_main`

## Context and decision drivers

Interactive requests and bulk evaluation/embedding workloads have different
latency, throughput, and price characteristics. The orchestrator must keep one
cost/policy boundary without making standalone use depend on an external batch
service.

## Considered alternatives

- sync only: simple but uneconomical for latency-tolerant work;
- make `pg-llm-batch` mandatory: breaks standalone modularity;
- duplicate cost policy in both services: creates contradictory evidence;
- shared routing contract with local and injected backends: selected.

## Decision

`RoutingPolicy` uses explicit hints and KV thresholds. Interactive work stays on
sync execution. Latency-tolerant work uses a `BatchBackend` or embedding backend.
Local in-process implementations preserve offline/standalone behavior;
`PgLlmBatchBackend` and configuration adapters preserve external ownership.
Usage from ordinary coordinator sync execution and coordinator-completed or
retrieved batch results enters the same prompt-safe ledger contract. Passthrough
and route streaming bypass that ledger on protected main; submit/poll alone does
not record completion usage.

## Consequences

Callers receive observable job states. External adapters add operational
dependencies but do not remove the interactive path. Cost comparison can use
one attribution vocabulary only for the coordinator paths that record usage.
Coordinator job handles and replay guards remain process-local.

## Failure and recovery

Submit/poll/retrieve failures remain non-success job states. Oversized embedding
inputs split under explicit limits. External outage does not convert a job to
complete or prevent local interactive requests.

## Security, privacy, and governance impact

The external backend receives only its versioned payload and purpose metadata.
It owns transport, authorization, persistence, retention, and job tenancy under
its contract; the orchestrator cannot infer those controls.

## Compatibility and migration

The local backend is the default. Adopting `pg-llm-batch` injects adapters and
config rather than changing caller schema. Backend identifiers and result
semantics remain stable.

## Verification and acceptance

Tests cover decision reasons, sync and batch use, submit/poll/retrieve,
embeddings splitting/reduction, attribution, malformed/partial results, and
dependency failure.

## Rollback and supersession

Route affected work to the local backend or disable latency-tolerant submission.
Supersede only with an adapter preserving job/evidence and standalone contracts.

## References

Chen et al. (2023); Ding et al. (2024); Ong et al. (2024). See
[the reference index](../REFERENCES.md).
