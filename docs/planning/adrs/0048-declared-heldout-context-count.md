---
id: "0048"
title: "Declare held-out context population"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0047-declared-latency-repetitions.md"
    relation: extends
success_criteria:
  - metric: "no hidden held-out population"
    target: "omitted or non-positive context_count fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_heldout_quality_requires_declared_context_count"
  - metric: "declared count is the quality loop"
    target: "ranking calls equal the declared context_count"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_heldout_quality_uses_declared_context_count"
---

# ADR 0048: Declare held-out context population

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing accuracy and decision-latency KPIs are averages over a held-out
context population. A hidden `TRAIN_CONTEXTS = 24` chose that population
without an operator declaration.

## Decision

In the context of the held-out warm-start harness, facing `TRAIN_CONTEXTS =
24`, we chose a required `context_count` declaration on evidence construction,
quality evaluation, and paired latency, and against restoring that constant as
a KPI default, to keep the population reconstructible, accepting that those
helpers without the argument fail closed.

The harness run writes 24 as this run's choice and records
`contexts_held_out` / `contexts_train`. Assignment and DIF helpers may still
read the same run declaration as a module constant. Production route/conduct
defaults stay locked.

## Alternatives considered

- Keep 24 as a module constant. Rejected: it hides the accuracy/latency
  population from the report consumer.
- Require `context_count` on every diagnostic helper in this slice. Rejected:
  assignment and DIF sample sizes remain later work.

## Consequences

Positive: the held-out population used for Brier, log loss, regret, and
decision-latency p50/p95 is reconstructible.

Negative: library callers of the three helpers must pass the declaration.

## Remaining work

Assignment-design trial count moves to ADR 0049. Other repository-authored
harness sample sizes stay open. This ADR is Proposed until independent
review and protected delivery.
