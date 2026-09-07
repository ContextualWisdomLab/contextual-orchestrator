---
id: "0045"
title: "Use coverage-neutral held-out interval keys"
status: proposed
proposed_date: "2026-09-07"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0044-declared-heldout-bootstrap-coverage.md"
    relation: extends
success_criteria:
  - metric: "no 95 in interval field names"
    target: "delta_ci95 and nested *_ci95 keys are absent; *_interval keys are present"
    source: "tests/test_psychometric_routing.py::test_heldout_report_keys_do_not_embed_coverage"
---

# ADR 0045: Use coverage-neutral held-out interval keys

- Status: Proposed
- Date: 2026-09-07
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

A buyer reading a held-out report must not infer 95% coverage from a field
name when coverage is a run declaration. `delta_ci95` hid that choice after
ADR 0044 required an explicit `bootstrap_confidence_level`.

## Decision

In the context of the held-out JSON report, facing nested `*_ci95` keys, we
chose coverage-neutral `*_interval` names and against keeping a 95 suffix or
dual keys, to keep the estimand in `bootstrap_confidence_level`, accepting
that existing reports must be regenerated.

Renamed fields: `delta_interval`, `paired_delta_interval`,
`query_delta_interval`, `accuracy_delta_interval`, and
`heldout_paired_delta_interval`. IRT parameter-interval diagnostics that
measure actual 95% coverage of standard-error intervals
(`interval_95_coverage_rate`) are unchanged.

Production route/conduct defaults stay locked.

## Alternatives considered

- Keep `*_ci95` names. Rejected: they contradict declared coverage.
- Emit both old and new keys. Rejected: dual names invite the same misread.

## Consequences

Positive: interval names no longer imply a coverage.

Negative: consumers of the previous JSON keys must read `*_interval`.

## Remaining work

Sequential-drift horizon, Wilson coverage, and censored no-alarm delays move
to ADR 0046. Other repository-authored harness sample sizes stay open. This
ADR is Proposed until independent review and protected delivery.
