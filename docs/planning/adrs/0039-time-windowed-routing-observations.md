---
id: "0039"
title: "Opt-in time-windowed routing observations"
status: proposed
proposed_date: "2026-08-29"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/routing_observation_store.py"
  - "contextual_orchestrator/model_group.py"
  - "contextual_orchestrator/orchestrator.py"
related:
  - path: "docs/planning/adrs/0032-model-group-cost-aware-discovery.md"
    relation: extends
success_criteria:
  - metric: "restart continuity"
    target: "an explicitly configured state database restores current-window observations"
    source: "tests/test_routing_observation_store.py"
  - metric: "retention boundary"
    target: "observations outside the configured wall-clock window do not affect routing"
    source: "tests/test_routing_observation_store.py"
---

# Opt-in time-windowed routing observations

## Context

Measured model-group routing currently keeps its Beta-Bernoulli success ledger
and Jacobson-style latency EWMA in one gateway process. That is useful local
evidence, but it resets on restart and cannot be shared by replicas. Persisting
unbounded history would allow an old provider incident to dominate a current
route, while decay or cross-model weights would introduce uncalibrated policy.

## Decision

Add a normalized `routing_observations` SQLite table behind the explicit
`--routing-observation-window-seconds SECONDS` option. The option requires the
existing `--state-db PATH`; without both settings, routing behavior stays
process-local and unchanged. Each transport or quality ledger writes one row
per completed attempt with its ledger name, opaque member id, wall-clock time,
success flag, measured latency when successful, and provider-reported output
tokens when available.

Each router refresh replays only rows at or after `now - window_seconds`, in
completion order, using the existing estimator and priors. Writes prune rows
outside the window. Separate short-lived SQLite connections and a transactional
write boundary permit multiple gateway processes to use the same database; a
storage error propagates so configured durable evidence is never silently
reported as local-only evidence. Non-stream success-observation requests
therefore fail closed. Provider-failure recording preserves the active provider
failure and logs the durable-evidence outage so failover can continue. A stream
may already have emitted provider bytes before its post-completion observation
write; that write failure is logged as degraded durable evidence and cannot
change the already-emitted response. Removed group members delete their
persisted rows. The Admin state
reports whether the policy is enabled, its window, and the literal
`time_window_only` retention policy.

This decision deliberately does not add calibrated decay, a fleet-wide sequence
cursor, a row-count policy, cross-model quality weighting, inferred provider
equivalence, or a production horizontal-scaling claim. Full-window replay is a
small correctness-first implementation; add incremental replay or a different
shared store only after measured fleet load justifies it. Provider-reported token
counts remain optional and are never inferred.

## Consequences

- Operators can preserve current-window transport and quality evidence across
  restarts and cooperating gateway processes.
- The default remains process-local, so existing deployments do not create a
  new database or change routing behavior.
- The selected window is a retention boundary, not a statistical calibration;
  production defaults remain unchanged until fleet-scale evidence and a decay
  policy are separately accepted.
- SQLite is appropriate for the current opt-in bounded slice. A high-throughput
  deployment may need a shared service or incremental replay after measurement,
  but that is intentionally not built speculatively here.

## References

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM Computer
Communication Review, 18*(4), 314–329. https://doi.org/10.1145/52325.52356

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data* [Preprint]. arXiv. https://arxiv.org/abs/2406.18665

SQLite. (2026). *Transaction*. https://www.sqlite.org/lang_transaction.html
