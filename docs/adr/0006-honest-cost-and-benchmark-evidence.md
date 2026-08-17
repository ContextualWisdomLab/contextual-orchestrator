# ADR-0006: Honest cost and benchmark evidence

## Status

`implemented_on_protected_main` for labeled token estimates, operator-supplied
prices, unpriced-model lists, and the prompt-safe usage ledger.

Comparable-budget learned routing, invoice-grade billing, and automatic
production-policy rewrite from benchmarks are **not** shipped.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Routing and orchestration decisions depend on cost, quality, latency, and
token evidence. Chen et al. (2023) show why a gateway should account for
per-request cost instead of treating model choice as free. Ong et al. (2024)
and Ding et al. (2024) show why routing evidence must stay comparable across
strong/weak or hard/easy arms.

Provider-reported usage, local token estimates, configured prices, benchmark
scores, and external invoices have different authorities. Combining them
without provenance can make an unpriced or weakly measured path appear better
than it is. NIST AI 600-1 asks for transparent measurement and
pre-deployment testing rather than fabricated assurance (National Institute
of Standards and Technology, 2024a).

## Considered alternatives

- Report one blended cost number: simple, but conceals unknowns and
  estimates.
- Trust provider marketing or a single benchmark run: neither reproducible
  nor workload-specific.
- Block all routing when any field is unknown: safe but removes useful
  partial evidence.
- Preserve source, method, uncertainty, and missingness per value: selected.

## Decision

Every cost, token, latency, quality, and benchmark fact identifies its source
as provider-reported, locally measured, configured, estimated, unknown, or
external. Unknown price remains unknown rather than zero. Models without an
operator-supplied price appear under `unpriced_models` with
`estimated_cost_usd: null`.

The usage ledger carries seven attribution dimensions: `account`, `service`,
`upstream_api`, `model_name`, `team`, `group`, and `company`. Raw prompt and
answer text are not part of the usage record.

Repository results never claim a live price, contractual bill, certification,
or general superiority.

## Consequences

Evidence is more verbose and some comparisons remain inconclusive. Operators
can distinguish accounting facts from routing estimates and can replay the
exact policy decision.

## Failure and recovery

Missing usage or prices produce explicitly incomplete evidence. An export
failure does not fabricate persistence. Recovery reconciles by immutable run
identity and marks irrecoverable gaps; it never imputes them as measurements.

## Security, privacy, and governance impact

Usage records exclude prompts, answers, secrets, and unnecessary PII
(International Organization for Standardization, 2022). Benchmark artifacts
contain only the minimum reproducibility data and cannot confer review,
release, or buyer-acceptance authority.

## Compatibility and migration

Existing numeric fields remain readable, but new writers supply provenance and
measurement status. Readers treat absent legacy provenance as unknown.

## Verification and acceptance

Tests cover reported versus estimated tokens, configured versus unknown
price, unpriced model lists, and prompt-safe export. A production-default
routing change additionally needs a predeclared quality threshold and a
locked evaluation set.

## Rollback and supersession

Rollback may disable a faulty estimator or benchmark policy but must retain
raw qualified evidence. Supersession requires a documented measurement model
and a reproducible migration of historical classifications.

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*
(arXiv:2305.05176) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM: Cost-efficient
and quality-aware query routing* (arXiv:2404.14618) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* (arXiv:2406.18665, Version 4) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2406.18665

National Institute of Standards and Technology. (2024a). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

International Organization for Standardization. (2022). *Information
security, cybersecurity and privacy protection — Information security
management systems — Requirements* (ISO/IEC 27001:2022).
https://www.iso.org/standard/27001

See also [docs/REFERENCES.md](../REFERENCES.md).
