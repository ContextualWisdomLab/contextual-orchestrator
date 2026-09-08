---
id: "0050"
title: "Declare held-out candidate-group DIF sample size"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0049-declared-assignment-trials.md"
    relation: extends
success_criteria:
  - metric: "no hidden DIF sample default"
    target: "omitted, non-positive, or odd sample_size fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_candidate_group_dif_requires_declared_sample_size"
  - metric: "declared count is the DIF population"
    target: "report sample_size equals the declared even count"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_candidate_group_dif_uses_declared_sample_size"
---

# ADR 0050: Declare held-out candidate-group DIF sample size

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing candidate-group DIF evidence must be reconstructible. A hidden
`DIF_SAMPLE_SIZE = 4_000` chose Monte Carlo precision for two equal cohorts
without an operator declaration.

## Decision

In the context of the held-out purified logistic DIF screen, facing
`DIF_SAMPLE_SIZE = 4_000`, we chose a required even `sample_size`
declaration and against restoring that constant, to keep the two-group
population reconstructible, accepting that `_validate_candidate_group_dif`
without the argument fails closed.

The harness run writes 4,000 as this run's choice and records `sample_size`.
Odd counts fail closed so the two cohorts stay equal. Production
route/conduct defaults stay locked.

## Alternatives considered

- Keep 4,000 as a module constant. Rejected: it hides the DIF population from
  the report consumer.
- Allow odd counts and drop one row. Rejected: silent truncation would hide
  the declared population.

## Consequences

Positive: DIF sample size is reconstructible from the report and the helper
signature.

Negative: library callers of `_validate_candidate_group_dif` must pass an
even positive count.

## Remaining work

Other repository-authored harness sample sizes stay open. This ADR is
Proposed until independent review and protected delivery.
