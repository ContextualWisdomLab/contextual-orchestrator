# ADR-0006: Honest cost and benchmark evidence

## Status

`accepted_architecture`

## Context and decision drivers

Routing and orchestration decisions depend on cost, quality, latency, and token
evidence. Provider-reported usage, local token estimates, configured prices,
benchmark scores, and external invoices have different authorities. Combining
them without provenance can make an unpriced or weakly measured path appear
better than it is.

## Considered alternatives

- report one blended cost number: simple, but conceals unknowns and estimates;
- trust provider marketing or a single benchmark run: current, but neither
  reproducible nor workload-specific;
- block all routing when any field is unknown: safe but unnecessarily removes
  useful partial evidence;
- preserve source, method, uncertainty, and missingness per value: selected.

## Decision

Every cost, token, latency, quality, and benchmark fact identifies its source as
provider-reported, locally measured, configured, estimated, unknown, or
external. Unknown price remains unknown rather than zero. Comparisons use fixed,
versioned tasks and scorers, repeated cells, comparable call/token budgets, and
full model/provider/policy assignments. Repository results never claim a live
price, contractual bill, certification, or general superiority.

Protected main does not yet satisfy the whole decision. Workflow-derived
spend/budget and `CostLedger` are separate authorities; the active `PriceBook`
uses ConfigStore while SQL `llm_price_entries` is dormant; missing ledger price
becomes `0.0`; and `cheapest_upstream()` is not used for selection. These facts
are recorded as gaps, not described as free or cost-optimized routing.

## Consequences

Evidence is more verbose and some comparisons remain inconclusive. Operators
can nevertheless distinguish accounting facts from routing estimates and can
replay the exact policy decision.

## Failure and recovery

Missing usage or prices produce explicitly incomplete evidence. An export
failure does not fabricate persistence. Recovery reconciles by immutable run
identity and marks irrecoverable gaps; it never imputes them as measurements.

## Security, privacy, and governance impact

Usage records exclude prompts, answers, secrets, and unnecessary PII. Benchmark
artifacts contain only the minimum reproducibility data and cannot confer
review, release, or buyer-acceptance authority.

## Compatibility and migration

Existing numeric fields remain readable, but new writers supply provenance and
measurement status. Readers treat absent legacy provenance as unknown.

## Verification and acceptance

Tests cover reported versus estimated tokens, configured versus unknown price,
unpriced model lists, prompt-safe export, degraded-store telemetry, repeated
benchmark cells, assignment completeness, and comparable budgets.

## Rollback and supersession

Rollback may disable a faulty estimator or benchmark policy but must retain raw
qualified evidence. Supersession requires a documented measurement model and a
reproducible migration of historical classifications.

## References

Chen et al. (2023), Ding et al. (2024), and Ong et al. (2024). Full APA 7
entries are in [the reference index](../REFERENCES.md).
