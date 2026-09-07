---
id: "0049"
title: "Declare held-out assignment-design trial count"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0048-declared-heldout-context-count.md"
    relation: extends
success_criteria:
  - metric: "no hidden assignment trial default"
    target: "omitted or non-positive trial_count fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_assignment_design_requires_declared_trial_count"
  - metric: "declared count is the logging loop"
    target: "ranking calls equal the declared trial_count"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_assignment_design_uses_declared_trial_count"
---

# ADR 0049: Declare held-out assignment-design trial count

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing inverse-propensity assignment evidence must be reconstructible.
A hidden `ASSIGNMENT_TRIALS = 24_000` chose Monte Carlo precision for the
logging-design RMSE without an operator declaration.

## Decision

In the context of the held-out epsilon-greedy logging screen, facing
`ASSIGNMENT_TRIALS = 24_000`, we chose a required `trial_count` declaration
and against restoring that constant, to keep the sample size reconstructible,
accepting that `_validate_assignment_design` without the argument fails
closed.

The harness run writes 24,000 as this run's choice and records `trials`.
Exploration rate and the 1.96 interval multiplier stay later work.
Production route/conduct defaults stay locked.

## Alternatives considered

- Keep 24,000 as a module constant. Rejected: it hides the assignment sample
  size from the report consumer.
- Declare exploration rate in the same slice. Rejected: it is a policy
  parameter, not the Monte Carlo trial count.

## Consequences

Positive: assignment-design trial count is reconstructible from the report
and the helper signature.

Negative: library callers of `_validate_assignment_design` must pass the
declaration.

## Remaining work

Other repository-authored harness sample sizes stay open. This ADR is
Proposed until independent review and protected delivery.
