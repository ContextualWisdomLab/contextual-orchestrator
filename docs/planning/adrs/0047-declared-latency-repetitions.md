---
id: "0047"
title: "Declare held-out decision-latency repetitions"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0046-declared-sequential-drift-horizon.md"
    relation: extends
success_criteria:
  - metric: "no hidden latency repetition default"
    target: "omitted or non-positive repetitions_per_context fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_paired_latency_requires_declared_repetitions"
  - metric: "declared count is the timing loop"
    target: "ranking calls equal two policies times contexts times declared repetitions"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_paired_latency_uses_declared_repetition_count"
---

# ADR 0047: Declare held-out decision-latency repetitions

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing decision-latency p50/p95 on the held-out harness must be
reconstructible. A hidden 200-repetition timing loop per context allocates
Monte Carlo precision without an operator declaration.

## Decision

In the context of paired held-out ranking timings, facing
`LATENCY_REPETITIONS = 200`, we chose a required `repetitions_per_context`
declaration and against restoring that constant, to keep the latency sample
size reconstructible, accepting that `_measure_paired_latency` without the
argument fails closed.

The harness run writes 200 as this run's choice and records
`latency_repetitions_per_context`. Nearest-rank p95 indexing is unchanged.
Production route/conduct defaults stay locked.

## Alternatives considered

- Keep 200 as a module constant. Rejected: it hides the latency sample size
  from the report consumer.
- Require the count on `run_benchmark` as well. Rejected for this slice: the
  timing helper is the allocation site; the harness entry already records the
  run choice. Expanding `run_benchmark` can follow with remaining sample sizes.

## Consequences

Positive: decision-latency repetition count is reconstructible from the report
and the helper signature.

Negative: library callers of `_measure_paired_latency` must pass the
declaration.

## Remaining work

Held-out context population moves to ADR 0048. Other repository-authored
harness sample sizes stay open. This ADR is Proposed until independent
review and protected delivery.
