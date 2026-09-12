# Optimizer score-domain recovery

Status: proposed; 2026-09-12. Owner: contextual-orchestrator evaluation API.

## Problem and contract

Both `optimize_orchestration` and `evolve_orchestration` document a caller quality
score in [0, 1]. Their common `_score_config` converted values to float but did
not validate them. NaN or infinity could reach sorting, recommendations and the
Pareto front; invalid pairs could hide behind a valid arithmetic mean.
This is input-contract enforcement, not evidence that a judge measures the
intended construct, that an IRT model fits, or that route quality improved.

## Decision and alternatives

Validate each converted score in the existing shared function, before its mean
is returned. Do not clamp, silently omit failed items, or validate only the mean:
each would change the caller's evidence or hide an invalid evaluation. Retain
Boolean predicates and valid fractional scores. No dependency or new service is
needed. Validation occurs after calls and cannot undo billed provider work.

## Reproduction

Base: `012beaacd0631f8cd3391c77744eeb626269b5de`.
RED: `40290df6`, 28 failed / 16 passed, 5.89s.
GREEN code: `982b553345623e006698950bd560d94b4038ed33`, 76 passed, 11.65s.
Run from a checkout with the project's test dependencies:

```sh
python -m pytest tests/test_optimizer_score_domain.py tests/test_optimizer.py tests/test_evolve_optimizer.py tests/test_batch_optimizer.py -q
```

The recovery run used the existing project-local Python environment, with source
imports from `/tmp/co-quality-score-recovery-20260912`. It is source integration
evidence, not an isolated installed-wheel check. All provider answers are mock
unit-test data. The historical September 9 source commits are unavailable in
the current object store; their full-test log is not current-head acceptance.

## Remaining acceptance

Run full checks and isolated installed-package tests, inspect the rendered
documentation, obtain independent current-head review and protected CI before
merge/release. Real accuracy and decision-latency KPIs still require an observed
cohort, independent adjudication, failure denominators and uncertainty estimates.
