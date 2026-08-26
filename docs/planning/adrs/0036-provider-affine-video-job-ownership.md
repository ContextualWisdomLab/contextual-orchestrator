---
id: "0036"
title: "Preserve provider ownership for asynchronous video jobs"
status: accepted
proposed_date: "2026-08-26"
accepted_date: "2026-08-26"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/video_jobs.py"
  - "contextual_orchestrator/server.py"
related:
  - path: "docs/planning/adrs/0034-anti-heuristic-routing-evidence.md"
    relation: constrained-by
success_criteria:
  - metric: "provider-affine video follow-up"
    target: "status and content requests use the exact agent that accepted submission"
    source: "tests/test_multimodal_model_group_http.py"
  - metric: "opaque ownership contract"
    target: "clients receive a gateway job id while provider job ids remain internal"
    source: "tests/test_video_jobs.py"
---

# Preserve provider ownership for asynchronous video jobs

## Context

Video submission can select among operator-declared eligible agents. A later
status or content request cannot repeat that selection: the provider job id is
valid only at the provider that accepted the submission. Model names, provider
ordering, and endpoint guesses are not evidence of ownership.

## Decision

After a provider accepts a video submission, the gateway records an opaque
gateway job id, the provider job id, the exact agent id, and submission time in
the existing job-registry boundary. Status and content requests resolve that
record and call the recorded agent without routing again. The provider id is
not returned to the client.

Video submission does not use immediate speculative racing when provider-side
job cancellation is unavailable. It follows the measured sequential failover
order and stops after the first accepted job, so no losing provider can retain
an unowned billable job. Synchronous capabilities may still use an
operator-declared equivalent-endpoint race under ADR 0034.

A provider response without a non-empty job id fails with 502 instead of
creating an untrackable resource. An unknown gateway id returns 404. If the
recorded agent was removed from configuration, follow-up returns 503 with an
operator action; it never selects a replacement provider. Disabling an agent
prevents new selection but does not invalidate ownership of work it already
accepted.

A configured owner that is temporarily unreachable also returns the same
redacted 503 rather than a generic 500. Provider responses are recursively
rewritten so an exact provider job id repeated in nested metadata or URLs is
replaced by the gateway id before crossing the public boundary.

The registry inherits the existing operator-configured lifecycle. With Valkey
configured, ownership survives process restart and is shared across replicas;
without it, the established standalone registry is process-local and makes no
durability claim. This decision adds no inferred TTL or new retention policy.

## Consequences

- Polling and content retrieval cannot cross provider boundaries.
- Provider identifiers and credentials remain behind the authenticated gateway.
- Operators that require restart or multi-replica continuity must configure the
  existing shared job registry.
- Removing an agent with outstanding jobs makes those jobs unavailable until
  that exact agent configuration is restored.

## References

Fielding, R. T. (2000). *Architectural styles and the design of network-based
software architectures* (Doctoral dissertation, University of California,
Irvine). https://www.ics.uci.edu/~fielding/pubs/dissertation/top.htm
