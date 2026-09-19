---
id: "0051"
title: "Declare held-out score-reliability sample size"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0050-declared-dif-sample-size.md"
    relation: extends
success_criteria:
  - metric: "no hidden reliability sample default"
    target: "omitted or non-positive sample_size fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_score_reliability_requires_declared_sample_size"
  - metric: "declared count is the reliability population"
    target: "sample_size_per_case equals the declared count"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_score_reliability_uses_declared_sample_size"
---

# ADR 0051: Declare held-out score-reliability sample size

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing posterior reliability evidence must be reconstructible. A hidden
`RELIABILITY_SAMPLE_SIZE = 1_200` chose Monte Carlo precision for weak- versus
strong-information cases without an operator declaration.

## Decision

In the context of the held-out empirical-reliability screen, facing
`RELIABILITY_SAMPLE_SIZE = 1_200`, we chose a required `sample_size`
declaration and against restoring that constant, to keep the population
reconstructible, accepting that `_validate_score_reliability` without the
argument fails closed.

The harness run writes 1,200 as this run's choice and records
`sample_size_per_case`. Production route/conduct defaults stay locked.

## Alternatives considered

- Keep 1,200 as a module constant. Rejected: it hides the reliability
  population from the report consumer.
- Declare FitConfig max_iter in the same slice. Rejected: it is optimizer
  budget, not the person-sample size.

## Consequences

Positive: reliability sample size is reconstructible from the report and the
helper signature.

Negative: library callers of `_validate_score_reliability` must pass the
declaration.

## Remaining work

Judge-effect sample size moves to ADR 0052. Other repository-authored
harness sample sizes stay open. This ADR is Proposed until independent
review and protected delivery.
