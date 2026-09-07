---
id: "0046"
title: "Declare sequential-drift horizon and record censored delays"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0045-heldout-coverage-neutral-interval-keys.md"
    relation: extends
success_criteria:
  - metric: "no hidden CUSUM horizon"
    target: "omitted replications, horizon_observations, change_after_observations, or confidence_level fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_sequential_drift_requires_declared_horizon_and_coverage"
  - metric: "no-alarm replications are evidence"
    target: "a threshold that never fires records censored delays instead of aborting"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_sequential_drift_records_horizon_censored_non_detections"
---

# ADR 0046: Declare sequential-drift horizon and record censored delays

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing sequential-drift KPIs are false-alarm rate and detection delay.
A hidden 500-replication, 250-observation, change-at-100 CUSUM screen that
aborts when a replication never alarms censors missed detections and bakes a
95% Wilson bound into the JSON field name.

## Decision

In the context of the held-out CUSUM screen, facing `assert alarm_observation
is not None`, a baked-in horizon, and `false_alarm_rate_upper_95`, we chose
required declarations and horizon-censored missed detections, and against
keeping the abort, to keep delay evidence reconstructible, accepting that
callers of `_validate_sequential_drift` must pass the run choices.

`_evaluate_sequential_drift_threshold` and `_validate_sequential_drift` take
keyword-only `replications`, `horizon_observations`,
`change_after_observations`, and `confidence_level`. `None`, non-positive
integers, `change_after >= horizon`, or a non-exclusive-unit-interval coverage
fail closed. Replications that never alarm are counted as censored and enter
the delay distribution at `horizon - change_after`. The Wilson upper bound
uses `statistics.NormalDist().inv_cdf` of the declared coverage and is stored
as `false_alarm_rate_upper_bound`. The harness run writes 500, 250, 100, and
the declared bootstrap coverage as this run's choices.

Production route/conduct defaults stay locked.

## Alternatives considered

- Keep the abort and hidden 250/100/500 constants. Rejected: they hide Monte
  Carlo precision and drop missed detections from the delay KPI.
- Treat censored delays as missing and report p95 among detections only.
  Rejected: that still censors non-detections from the delay distribution.
- Kaplan-Meier delay estimation. Rejected for this slice: the synthetic
  horizon is declared and finite; a survival estimator would change the
  estimand without buyer time series.

## Consequences

Positive: no-alarm replications remain evidence; coverage is not implied by a
JSON field name; horizon and change-point are reconstructible.

Negative: a threshold that rarely fires reports a larger delay p95 because
missed detections sit at the remaining horizon.

## Remaining work

Held-out decision-latency repetitions move to ADR 0047. Other
repository-authored harness sample sizes stay open. This ADR is Proposed
until independent review and protected delivery.
