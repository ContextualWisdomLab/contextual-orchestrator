---
id: "0053"
title: "Declare held-out item-covariate sample size"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0052-declared-judge-sample-size.md"
    relation: extends
success_criteria:
  - metric: "no hidden item-covariate sample default"
    target: "omitted, boolean, or sample_size below two fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_item_covariate_requires_declared_sample_size"
  - metric: "declared count is the person population"
    target: "report sample_size equals the declared count"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_item_covariate_uses_declared_sample_size"
---

# ADR 0053: Declare held-out item-covariate sample size

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing item-side language/domain contrast evidence must be
reconstructible. A hidden `ITEM_COVARIATE_SAMPLE_SIZE = 1_200` chose Monte
Carlo precision without an operator declaration.

## Decision

The two-group contrast requires at least two observations. A declaration of
one produces only group zero while the covariate matrix contains two groups;
reject it before fitting rather than exposing a downstream matrix-shape error.
This is a structural minimum, not evidence of adequate statistical power.
Boundary tests retain both groups for counts two, three, and forty. The
full-size report test independently pins this run's declared count to 1,200.

In the context of the held-out multigroup item-covariate screen, facing
`ITEM_COVARIATE_SAMPLE_SIZE = 1_200`, we chose a required `sample_size`
declaration and against restoring that constant, to keep the person
population reconstructible, accepting that `_validate_item_covariate_effect`
without the argument fails closed.

The harness run writes 1,200 as this run's choice and records `sample_size`.
Optimizer max-iter stays later work. Production route/conduct defaults stay
locked.

## Alternatives considered

- Keep 1,200 as a module constant. Rejected: it hides the person population
  from the report consumer.
- Declare max_iter in the same slice. Rejected: it is optimizer budget, not
  the sample size.

## Consequences

Positive: item-covariate sample size is reconstructible from the report and
the helper signature.

Negative: library callers of `_validate_item_covariate_effect` must pass the
declaration.

## Remaining work

Other repository-authored harness sample sizes stay open. This ADR is
Proposed until independent review and protected delivery.
