# ADR-0001: Route and conduct test-time compute

## Status

`implemented_on_protected_main`

## Context and decision drivers

One compatible endpoint must handle simple requests economically and complex
requests with explicit decomposition and verification. Fugu, Conductor, and
TRINITY show complementary routing and orchestration patterns, but they do not
justify spending more calls on every request or claiming learned behavior.
Correctness, evidence, controllability, reliability, and comparable budgets are
primary drivers; latency is a measured guardrail.

## Considered alternatives

- always call one model: simple and cheap, but cannot expose structured
  verification or multi-agent evidence;
- always run a fixed multi-agent workflow: auditable, but wastes compute and
  confounds quality comparisons;
- learned coordinator immediately: unsupported without a versioned evaluation
  set and operational reward data;
- deterministic route/conduct split with measurable policy: selected.

## Decision

`TaskOrchestrator.complete()` chooses `route` or `conduct` from explicit caller
mode and a versioned policy. Route selects one eligible worker. Conduct executes
a bounded template or validated generated plan with explicit roles and access
lists. New recursion, topology, or reasoning-effort knobs require hard call/token
caps and comparable-budget ablations.

## Consequences

The standalone runtime stays deterministic and testable. Deep orchestration may
improve difficult tasks but has higher cost and cannot claim live synthesizer
streaming before synthesis completes. Policy changes require evaluation replay.

## Failure and recovery

Invalid generated plans fall back to the bounded template. Budget exhaustion
fails before extra provider calls. If conduct quality is not better under a
comparable budget, revert affected workload cells to route or the last accepted
policy.

## Security, privacy, and governance impact

More steps create more provider exposure. Access lists, call bounds, provider
exclusions, and purpose-bound payload minimization apply to every step. A deeper
workflow never expands tool or credential authority.

## Compatibility and migration

The public API remains one model-like surface. New policy fields default to
current deterministic behavior and require trace versioning.

## Verification and acceptance

Route/conduct contract tests, access-list tests, fixed-task comparable-budget
evaluation, per-cell call/token evidence, uncertainty, and exact-head coverage
are required. Learned replacement additionally needs repeatable superiority over
the deterministic baseline.

## Rollback and supersession

Rollback selects the prior policy without changing request schema. Supersede
only with an ADR documenting evaluation data, budget parity, failure behavior,
and migration.

## References

Fugu Team, Sakana AI (2026); Nielsen et al. (2025); Xu et al. (2025). Full APA
7 entries are in [the reference index](../REFERENCES.md).
