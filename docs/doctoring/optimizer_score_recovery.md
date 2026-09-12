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

### Subsequent review boundaries (2026-09-12)

PR #1137 comment 5645316918 reports a local batch-cardinality repair with
218 passing tests but supplies no commit or worktree. The reviewed remote
head is `bf4561b541a1d6f3194ac807d96f5038bc7a8163`; the PR is Draft.
Our refs/reflog and registered-worktree search did not locate that descendant.
At local `f8cdaa413b8ce07d378ce933767e2638ccda10c0`, the shared evaluator still
uses unchecked `zip(tasks, records)`. Do not treat the comment's unpublished
test count as current-source acceptance. Request the exact patch provenance
before integrating; preserve both the existing usage repair and valid delta.

The reproduced boundary is a custom batch engine returning fewer records than
tasks, not evidence that the real `TaskOrchestrator.batch_route` drops outputs.
That implementation already validates provider results. Missing and extra
custom-engine records must be rejected before callbacks can rank partial data,
while retaining incurred usage through the shared exception path.

Calibration is a separate contract question: `_model_judge` resolves the
fast-mlsirm owner and fails closed if unavailable; the generic optimizer
callback does not itself carry calibration provenance. A bounded callback
score is not a calibrated psychometric outcome or production-policy authority.
Retain deterministic experimental evaluation while specifying released owner
evidence for production eligibility. Do not claim this scalar guard removed
an existing mandatory callback-calibration gate without source evidence.

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
Python 3.10.20 installed-wheel follow-up also passed all 216 tests in 13.64s
(session 58812, exit 0). The same frozen wheel was installed in
`/tmp/co-quality-package-85580612.OnW9XK/installed310`; execution from `/tmp`
used `-I` and asserted the installed import path. This environment resolved the
wheel's declared runtime dependencies plus pytest 9.1.1, rather than syncing
the Python 3.14 acceptance lock; it is not lock-parity or full-suite evidence.
Resolved differences included cryptography 50.0.1, protobuf 7.36.1,
googleapis-common-protos 1.75.3, idna 3.19 and typing-extensions 4.16.0.
No runtime or test files changed between frozen 85580612 and a9134aee.

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

## Released calibration boundary inspection — 2026-09-12

At local `b04dc9cec7636a764aa368324f5ac3ef0a5359fa`, six tests failed, but
three were subsequently identified as fixture-mode errors rather than batch
cardinality reproductions; the corrected RED is recorded below. No runtime
cardinality repair existed at that historical checkpoint. The unlocated
218-test descendant is still not acceptance evidence.

The hash-locked `fast-mlsirm==0.9.1` installed for the separate cache acceptance
contains `fast_mlsirm.judge_calibration`. Its module SHA-256 is
`e51b8a8ef5b7da331b8572db40b5cc049bfa29d3034d66ab584c81d2c10c21f6`.
Inspection covered lines 1–240 and 395–765, including report construction,
serialization and the entire `evaluate_paired_calibration` function. The module
explicitly calls its controls diagnostic evidence only. It retains failed
outcomes, category occupancy and paired score changes; `gold_exact_agreement`
uses the explicitly reported gold-scored subset, not every admitted case.
The report does not emit a production-eligibility decision, a confidence
interval or an independently verified holdout attestation. A caller-provided
`held_out` label is metadata, not proof of independent evaluation.

DeepWiki suggested this module supplied production-ranking eligibility. The
inspected released code does not support that assertion; treat that response
as a navigation hint, not evidence. Reuse the owner's diagnostic contract,
but do not infer calibration approval from package availability, successful
IRT projection or a bounded scalar score. The next owner/consumer contract
must bind validation evidence to the actual rubric, judge revision, population
and independent cohort before authorizing production changes. This bounded
inspection does not establish that no other owner module or newer release
provides such a contract, and adds no consumer-side replacement implementation.

## Cardinality repair and corrected RED receipt

Re-execution at `51dd1f65` found that the earlier six-failure count combined
three genuine missing-guard failures with three fixture errors: `optimize`
omitted `mode="route"`, so its test engine reached the nonbatch path and raised
`AttributeError`. The earlier count did not prove six batch-path reproductions.
Test-only `df4e7ac7` explicitly selects route mode; session `89770` then produced
six `DID NOT RAISE ValueError` failures in 0.86s, 184 deselected. Log:
`/tmp/co-cardinality-red-route-20260912.log`.

Runtime `090b4ec841cfc78b45248b561f1cef6396b57429` rejects a batch result count
different from the task count before any quality callback. Both optimizers use
this shared boundary; the existing exception path retains incurred usage.
This independently verified two-line repair is not claimed to reconstruct or
adopt the unlocated 218-test patch. No predecessor delta or review was discarded.
Equal-count custom results still require their provider's ordering/identity
contract; cardinality alone does not establish semantic task/result alignment.

Frozen source verification: **222 focused tests in 7.28s**, `-W error`, and
**3,791 passed, 2 skipped in 164.54s**, full process `61076`, log
`/tmp/co-quality-full-090b4ec8.log`. Independent bounded review found no regression
in either caller or usage preservation. Full source used the existing root
Python environment and unchanged read-only native namespace.

Separate installed-core verification used archive
`/tmp/co-cardinality-wheel-090b4ec8.fwO2im`, Python 3.14.6, the 46 hash-locked
requirements and pytest 9.1.1. Wheel SHA-256:
`ca295b0b5f9d73ae7c1c1d4df5b86e387a57975a9ac13cc2cfdb63d5e557861e`.
Initial process `47038` failed collection because a sibling test helper was
absent from the test search path. Process `89080` added only the archived tests
directory, used `python -I` from `/tmp`, asserted the installed core import,
then passed **222 tests in 13.57s** with importlib mode and `-W error`.
Do not add the package source root to conceal installed-package failures.

## Existing owner contract, not a new consumer manifest

Independent owner inspection found `validation_profile.py` on protected owner
revision `493326f2de49ea1704da0ded19868ed05d2fe00f`, binding protocol, rubric,
population, model fingerprints and classified evidence references. Tag v0.9.1
at `09f762ded35786dd1078222a4577ff09d649816f` lacks that module. Extend the
existing owner contract rather than create a parallel CO manifest.
[Owner PR #1737](https://github.com/ContextualWisdomLab/fast-mlsirm/pull/1737),
head `6a0e43e10192895703cf18c5f50fdfb0fa73cc76`, is a Draft preregistration
chronology successor, not a released dependency. Its failed aggregate
[job 100978763523](https://github.com/ContextualWisdomLab/fast-mlsirm/actions/runs/33820461734/job/100978763523)
reports `python-matrix result=cancelled`; this is not evidence of a validation
source defect. Cancellation cause and actual current-head test/review evidence
remain unresolved. Preserve the owner successor and release boundary.

PR #1137 remains Draft pending the separate psychometric evidence contract and
current-head hosted review. The cardinality repair neither authorizes production
ranking nor proves customer accuracy/latency improvement.
