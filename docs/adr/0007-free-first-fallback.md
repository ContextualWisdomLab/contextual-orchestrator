# ADR-0007: Free-first fallback without invented availability

## Status

`not_implemented_on_protected_main`

Protected `main` retries transient failures and fails over to the next
capability-matched agent. It does **not** implement an opt-in free-first
price policy. This ADR records the accepted target so later work cannot treat
unknown price as free.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Some providers expose zero-price or promotional model access, but price,
capacity, eligibility, and policy change independently. Chen et al. (2023)
motivate cost-aware selection. Ding et al. (2024) and Ong et al. (2024)
require that a cheaper path remain quality-aware. A free-first policy can
reduce spend only when the candidate is genuinely eligible and the fallback
does not weaken quality, privacy, reliability, or budget controls.

## Considered alternatives

- Always select the cheapest configured price: ignores availability and
  quality.
- Hard-code a provider's free model list: rapidly stale and
  provider-specific.
- Treat unknown price as free: financially misleading (see
  [ADR-0006](0006-honest-cost-and-benchmark-evidence.md)).
- Select only reviewed eligible zero-price candidates, then use the normal
  bounded fallback policy: selected as the target.

## Decision

Free-first is an opt-in policy over operator-supplied price and eligibility
evidence. A candidate must be enabled, non-excluded, compatible, and
explicitly classified as zero-price for the relevant dimensions. Unknown
price or availability is not free. Failures use the existing bounded
retry/failover and budget path; free status never grants extra context or
authority.

Until this policy ships, protected `main` must not describe itself as
free-first or cost-optimized beyond configured prices and labeled estimates.

## Consequences

Some nominally free opportunities will be skipped when evidence is
incomplete. Selection remains portable and auditable rather than depending on
a vendor catalog embedded in domain code.

## Failure and recovery

Stale price, missing eligibility, quota failure, or provider degradation
removes the candidate from that decision and records the reason. Recovery
refreshes operator evidence and replays fixed evaluation cells before
re-enabling policy.

## Security, privacy, and governance impact

A lower price cannot override provider allowlists, data-use restrictions,
credential policy, tenant purpose, or model exclusions (National Institute of
Standards and Technology, 2024a). Price evidence carries source and review
time without including secrets.

## Compatibility and migration

The default policy remains protected-main selection. Enabling free-first adds
a versioned policy field; clients that do not supply it retain current
behavior.

## Verification and acceptance

Acceptance requires exact-head tests for zero, unknown, and non-zero price,
stale availability, exclusions, quota failure, fallback bounds, stable
traces, prompt-safe evidence, and comparable-budget quality.

## Rollback and supersession

Disable the policy flag and retain its decision trace. A replacement must
state price authority, freshness, eligibility, quality floor, and failure
semantics.

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

See also [docs/REFERENCES.md](../REFERENCES.md).
