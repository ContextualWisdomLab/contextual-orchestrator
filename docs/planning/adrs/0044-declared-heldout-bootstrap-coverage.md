---
id: "0044"
title: "Declare held-out paired-bootstrap coverage"
status: proposed
proposed_date: "2026-09-07"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0042-declared-paired-bootstrap-coverage.md"
    relation: extends
success_criteria:
  - metric: "no hidden held-out interval default"
    target: "omitted resample_count, confidence_level, or seed fails closed"
    source: "tests/test_psychometric_routing.py::test_paired_bootstrap_interval_requires_declared_coverage"
---

# ADR 0044: Declare held-out paired-bootstrap coverage

- Status: Proposed
- Date: 2026-09-07
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing accuracy and decision-latency intervals on the psychometric
held-out harness must be reconstructible. A hidden 2,000-sample 95% interval
is Monte Carlo precision chosen by the repository, not a declared analysis.

## Decision

In the context of the held-out warm-start harness, facing
`BOOTSTRAP_SAMPLES = 2_000` and a baked-in 95% percentile, we chose required
declarations and against restoring those constants, to keep coverage explicit,
accepting that `run_benchmark()` without kwargs fails closed.

`_paired_bootstrap_mean_ci` takes keyword-only `resample_count`,
`confidence_level`, and `seed`. Percentile indices keep the existing
floor/ceil mapping so historical synthetic fixtures stay comparable; a
coverage that cannot be represented with the resample count fails closed.
The script entry passes 2,000, 0.95, and seed 568 as this run's choices.
The report records `bootstrap_samples`, `bootstrap_confidence_level`, and
`bootstrap_seed`.

Production route/conduct defaults stay locked. Nested `*_ci95` JSON key names
remain a later naming slice. Other harness sample sizes (assignment trials,
DIF, reliability) are unchanged.

## Alternatives considered

- Keep 2,000 and 0.95 as module constants. Rejected: they hide Monte Carlo
  precision from the report consumer.
- Switch to the NIM integer-index formula from ADR 0042. Rejected for this
  slice: it would move the 2,000-sample lower index and invalidate existing
  synthetic fixtures without a new estimand.

## Consequences

Positive: held-out interval coverage is reconstructible from the report and
the script entry.

Negative: library callers of `run_benchmark` and the calibration helper must
pass the declarations.

## Remaining work

Other repository-authored harness sample sizes stay open. Nested `*_ci95`
key names still embed 95. This ADR is Proposed until independent review and
protected delivery.
