---
id: "0042"
title: "Declare paired-bootstrap coverage and comparison pairs"
status: proposed
proposed_date: "2026-09-07"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/nim_benchmark.py"
related:
  - path: "docs/planning/adrs/0034-anti-heuristic-routing-evidence.md"
    relation: extends
success_criteria:
  - metric: "no hidden interval default"
    target: "omitted resample_count or confidence_level fails closed"
    source: "tests/test_nim_benchmark.py::test_paired_bootstrap_rejects_undeclared_or_invalid_coverage"
  - metric: "no baked-in policy subset"
    target: "omitted comparison_pairs fails closed; unobserved pairs are skipped, not invented"
    source: "tests/test_nim_benchmark.py::test_paired_policy_comparisons_reject_undeclared_or_invalid_pairs"
---

# ADR 0042: Declare paired-bootstrap coverage and comparison pairs

- Status: Proposed
- Date: 2026-09-07
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

A buyer comparing `route` and `conduct` needs to know which policies were
compared and how the uncertainty interval was formed. A hidden 2,000-resample
95% interval, or a hard-coded conduct/route/cheapest/hindsight subset, cannot
be defended as measurement design. The operator must declare resample count,
percentile coverage, and policy pairs for each run.

## Decision

In the context of NIM paired policy evidence, facing hidden 2,000-resample
95% intervals and a baked-in comparison subset, we chose required declarations
and against restoring those constants or auto-comparing every observed pair,
to keep the estimand explicit, accepting that a run without flags fails closed
and that undeclared hindsight comparisons are omitted.

`paired_bootstrap_mean_difference` takes keyword-only `resample_count`,
`confidence_level`, and `seed`. `None` is a fail-closed sentinel, not a
statistical default. Coverage must be a finite exclusive unit interval. The
percentile indices follow Efron and Tibshirani (1993); if the lower and upper
indices collapse, the declaration cannot be represented and the run fails.
The method name is `paired_bootstrap_percentile`; coverage is a numeric field.

`paired_policy_comparisons` takes declared `comparison_pairs`. Empty, malformed,
duplicate, or identical-name pairs fail closed. Unobserved or disjoint pairs
are omitted rather than imputed. Hindsight identity remains a separate
measurement; comparing against it requires an explicit pair.

Report schema 4.0.0 records the declarations in provenance. Production
route/conduct defaults stay locked. Token and workflow-depth budgets are the
successor slice in ADR 0043.

## Alternatives considered

- Keep 2,000 and 0.95 as code defaults. Rejected: they hide Monte Carlo
  precision and coverage from the report consumer.
- Auto-compare every observed locked policy pair. Rejected for this slice:
  exhaustive pairing is a different estimand and would change dry-run reports
  without an operator declaration. It can be declared later as an explicit
  pair list.
- Adopt RankWeave's released comparison API. Rejected: v0.18.0 does not accept
  generic response times or a paired percentile of mean differences.

## Consequences

Positive: interval coverage and compared policies are reconstructible from the
report and the workflow flags.

Negative: existing CLI, workflow, and library callers must pass the
declarations; schema 3 reports cannot be reused.

## Remaining work

Token and workflow-depth budgets move to ADR 0043. Held-out bootstrap
coverage moves to ADR 0044. This ADR is Proposed until independent review
and protected delivery.
