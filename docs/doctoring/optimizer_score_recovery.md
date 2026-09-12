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

The follow-up test-only commit `10bfd868` extends mode/accounting
coverage: 176 focused tests passed in 7.83s across route/auto/conduct,
both optimizers, and both values of the batch flag. Rejected NaN evaluations
retain both completed workflow records and run counts; the actual batch path
also retains the expected reported output-token total. No runtime code changed.
This does not retroactively extend the 44-case installed test's route-only scope.

## PR #1137 factory-discard review repair

The retained-engine assertions above did not cover a factory that constructs
an engine without retaining it. Review of `5240315f` identified that an invalid
score unwound before callers could recover its completed-call accounting.
RED commit `4369e702` reproduced 36 failures across both optimizers, all three
modes, both batch flags, and invalid-domain, callback and float-conversion
errors (`/tmp/co-quality-usage-red-20260912.log`, 3.92s).

The shared evaluation path now attaches `optimizer_usage` to the original
exception, preserving its type and identity. This ordered tuple includes
earlier completed evaluations and the failed evaluation. Each receipt contains
an evaluation index and an allowlisted aggregate usage snapshot, never candidate
names, configuration, model identifiers, prompts or answers. Its scope is
explicitly `cumulative_engine_snapshot`: preexisting work is included and reused
engines may overlap. Do not sum these receipts as invocation-only cost. Cost and
token counts retain their existing unavailable values. If analytics itself
fails, that receipt has unavailable status and null totals; its failure does
not replace the original exception or fabricate zero spend.

This is caller-accessible failure evidence, not durable billing storage. Factory
construction failures before entering the shared evaluator and process-level
termination are outside this repair. Successful return shapes are unchanged.
The final focused run passed 214 tests in 10.68s, including non-retained factories,
prior successful evaluations, preexisting engine usage, original exception
identity and unavailable analytics (`/tmp/co-quality-usage-green-final-20260912.log`).
At that checkpoint, full-suite, installed-wheel and rendered-document checks
were pending; the later frozen-repair receipt below supersedes that status.

Independent follow-up review found two compatibility edges, reproduced at
`6597712f` (2 failed, 3.36s): custom engines may return only the previously
required `totals.cost_usd`, and custom exceptions may expose a read-only
`optimizer_usage` property. Missing optional totals now remain null. For a
read-only exception attribute, the first repair used a JSON exception note.
The compatibility-focused full optimizer selection passed 216 tests in the
run recorded at `/tmp/co-quality-usage-compat-green.log`.

That note fallback was superseded: JSON serialization could itself reject a
custom engine's Decimal cost, and `BaseException.add_note` is unavailable on
supported Python 3.10. RED `d1a81643` reproduced the masking error (1 failed,
2.05s; `/tmp/co-quality-decimal-red.log`). Receipts are now stored directly in
the original exception's instance dictionary. Normal exceptions expose
`error.optimizer_usage`; when a subclass shadows that name with a property,
use `vars(error)["optimizer_usage"]`. No serialization or Python 3.11 API is
needed, and numeric values are not coerced.

The preceding frozen `b6fec962` full suite passed 3785 tests with 2 skips in
168.62s (`/tmp/co-quality-full-b6fec962.log`). This is historical evidence for
that revision, not current-repair full-suite acceptance.

## Frozen repair acceptance: 85580612

At `855806125a640d238850e575c1118bf4379f7e2d`, the full source suite passed
**3785 tests, 2 skipped in 200.11s**, exit 0 (session 78573;
`/tmp/co-quality-full-85580612.log`). Source and environment remained unchanged.

An independent Git archive built a wheel and installed it non-editably into
`/tmp/co-quality-package-85580612.OnW9XK/installed`, using hash-locked runtime
dependencies and pytest 9.1.1. From `/tmp`, Python 3.14.6 with `-I` imported
the installed package, asserted its site-packages location, and ran
`test_optimizer_score_domain.py`, `test_optimizer.py`,
`test_batch_optimizer.py`, and `test_evolve_optimizer.py`: **216 passed in
15.05s**, exit 0 (session 38230). Wheel SHA-256:
`d62e05d3d32dde50ba9f6687b03319a4661dafa5650b25301d4b132061527593`.
These are mock-provider behavioral checks, not observed customer KPI evidence.
Python 3.10 execution remains unverified.

Visual follow-up inspected the actual browser rendering of `bf4561b5` at
`http://127.0.0.1:18769/optimizer`, English, 1265 × 712. Three overlapping
screenshots were opened directly, covering the factory-discard section through
the final acceptance boundaries. Text, long hashes and paths wrapped without
horizontal clipping or overlap; heading spacing and contrast were legible.
The historical pending-status paragraph was misleading beside the new receipt
and is corrected here. This was a local documentation preview, not product UI;
its exporter navigation/title was inherited preview furniture. Narrow layouts,
other locales, link destinations and the revised paragraph are not visually
accepted by those captures. Images are retained in this task's browser outputs.

This follow-up preserves the existing PR and its valid delta. Push the repair
non-forcibly for fresh review of the factory-discard finding; do not resolve
the review or infer approval from local test success.

Obtain protected current-head CI and formal independent approval before
merge/release; local review does not satisfy GitHub approval rules.
Real accuracy and decision-latency KPIs still require an observed
cohort, independent adjudication, failure denominators and uncertainty estimates.
