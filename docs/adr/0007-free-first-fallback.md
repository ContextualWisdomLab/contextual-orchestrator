# ADR-0007: Free-first fallback without invented availability

## Status

`active_pr` — implementation and evidence are isolated to PR #94 and are not
protected-main behavior.

## Context and decision drivers

Some providers expose zero-price or promotional model access, but price,
capacity, eligibility, and policy change independently. A free-first policy can
reduce spend only when the candidate is genuinely eligible and the fallback
does not weaken quality, privacy, reliability, or budget controls.

## Considered alternatives

- always select the cheapest configured price: ignores availability and quality;
- hard-code a provider's free model list: rapidly stale and provider-specific;
- treat unknown price as free: financially misleading;
- select only reviewed eligible zero-price candidates, then use the normal
  bounded fallback policy: selected.

## Decision

Free-first is an opt-in policy over operator-supplied price and eligibility
evidence. A candidate must be enabled, non-excluded, compatible, and explicitly
classified as zero-price for the relevant dimensions. Unknown price or
availability is not free. Failures use the existing bounded retry/failover and
budget path; free status never grants extra context or authority.

## Consequences

Some nominally free opportunities will be skipped when evidence is incomplete.
Selection remains portable and auditable rather than depending on a vendor
catalog embedded in domain code.

## Failure and recovery

Stale price, missing eligibility, quota failure, or provider degradation removes
the candidate from that decision and records the reason. Recovery refreshes
operator evidence and replays fixed evaluation cells before re-enabling policy.

## Security, privacy, and governance impact

A lower price cannot override provider allowlists, data-use restrictions,
credential policy, tenant purpose, or model exclusions. Price evidence carries
source and review time without including secrets.

## Compatibility and migration

The default policy remains protected-main selection. Enabling free-first adds a
versioned policy field; clients that do not supply it retain current behavior.

## Verification and acceptance

Acceptance requires exact-head tests for zero/unknown/non-zero price, stale
availability, exclusions, quota failure, fallback bounds, stable traces,
prompt-safe evidence, and comparable-budget quality. PR #94 must independently
satisfy protected repository gates before this status changes.

## Rollback and supersession

Disable the policy flag and retain its decision trace. A replacement must state
price authority, freshness, eligibility, quality floor, and failure semantics.

## References

Chen et al. (2023), Ding et al. (2024), and Ong et al. (2024). See
[the reference index](../REFERENCES.md).
