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

### Verified checkpoint at 321409b0

The full source suite completed with **3645 passed, 2 skipped in 266.32s**
(exit 0; `/tmp/co-quality-recovery-full-321409b0.log`). Independent read-only
review found no actionable implementation defect; invalid auto/conduct scores
and post-rejection usage assertions remain explicit coverage gaps.

The exact Git archive built successfully with `uv build --wheel` and installed
non-editably into `/tmp/co-quality-package-321409b0.RRwUQQ/installed` after
hash-locked dependency installation. Wheel SHA-256:
`c0992936db4e8a82b76ae5685964bd4793612614374e04b62cf1107d1e538e47`.
The first build attempt used an old build environment without the `build`
module and failed before building; the isolated `uv build` replaced that path.
Installed behavioral acceptance subsequently passed 44 public-API cases using
`installed/bin/python -I installed_score_check.py` from `/tmp`. The printed
module path was the isolated environment's `site-packages`, not the source
checkout. The stdlib-only acceptance script exercised optimize/evolve and
serial/batch route calls, rejecting seven invalid value sets and preserving
four valid sets per combination. It remains mock-provider unit evidence.

Visual inspection: directly viewed the local browser rendering at
`http://127.0.0.1:18765/`, revision 321409b0, English, 1265 × 712 viewport.
Overlapping top/bottom captures showed readable headings, wrapped command and
revision text, and no horizontal clipping or overlap. This is a documentation
preview only; narrow viewports, other locales and product UI were not inspected.

Obtain protected current-head CI and formal independent approval before
merge/release; local review does not satisfy GitHub approval rules. Extend
invalid-score coverage to auto/conduct and retained usage before claiming all
evaluation-path coverage. Real accuracy and decision-latency KPIs still require an observed
cohort, independent adjudication, failure denominators and uncertainty estimates.
