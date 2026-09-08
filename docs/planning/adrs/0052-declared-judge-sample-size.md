---
id: "0052"
title: "Declare held-out judge-effect sample size"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0051-declared-reliability-sample-size.md"
    relation: extends
success_criteria:
  - metric: "no hidden judge sample default"
    target: "omitted or non-positive sample_size fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_judge_effects_requires_declared_sample_size"
  - metric: "declared count is the rater population"
    target: "report sample_size equals the declared count"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_judge_effects_uses_declared_sample_size"
---

# ADR 0052: Declare held-out judge-effect sample size

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing judge-severity evidence must be reconstructible. A hidden
`JUDGE_SAMPLE_SIZE = 1_000` chose Monte Carlo precision for a fully crossed
many-facet design without an operator declaration.

## Decision

In the context of the held-out many-facet Rasch screen, facing
`JUDGE_SAMPLE_SIZE = 1_000`, we chose a required `sample_size` declaration
and against restoring that constant, to keep the person population
reconstructible, accepting that `_validate_judge_effects` without the
argument fails closed.

The harness run writes 1,000 as this run's choice and records `sample_size`.
Production route/conduct defaults stay locked.

## Alternatives considered

- Keep 1,000 as a module constant. Rejected: it hides the rater-design
  population from the report consumer.
- Declare item and judge counts in the same slice. Rejected: those are the
  known facet structure of the synthetic design, not the Monte Carlo person
  sample.

## Consequences

Positive: judge-effect sample size is reconstructible from the report and the
helper signature.

Negative: library callers of `_validate_judge_effects` must pass the
declaration.

## Remaining work

Item-covariate sample size moves to ADR 0053. Other repository-authored
harness sample sizes stay open. This ADR is Proposed until independent
review and protected delivery.
