# Contextual Orchestrator: Product & Technical Gap Baseline

## 2026-09-19 free multimodal review routing — Proposed

Canonical owner PR
[#1203](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1203)
with functional repair `7f30351ccb36bb676ad0b23fe71ea1cce9f98645`
(tree `157468c88470e93dc2f3e19f03acbf34ff32219f`) repairs the
`orchestrator/free` image-admission boundary used by the proposed
`ContextualWisdomLab/.github` DOCX/HWPX review leaf #2281. Five RED
regressions proved that Responses conversion selected a higher-priority
text-only model, template planning and the model judge dropped
`input:image`, mixed-case discovery evidence was unroutable, and the changed
admission predicate was still published as readiness contract v1. Follow-up
RED cases then proved that proxy failover and realtime judging could lose the
image requirement, explicit image-only rows entered the mixed envelope, and
the first fix also rejected documented legacy `vision` agents with no
`input:*` evidence. A later endpoint regression proved that preflight and
pool admission still rejected an endpoint-local image-capable free agent
before request-aware selection.

The owner now carries normalized image evidence through Responses, template
roles, conducted invocation, proxy failover, realtime judging, and model
judging; readiness contract v2 records the predicate change. Explicit
`input:image` without `input:text` is rejected, while legacy `vision` with no
`input:*` declaration remains eligible. Endpoint preflight, Chat Completions,
and Responses now apply that same request-shaped pool boundary; endpoints
without local eligible capacity still fail closed. Exact head
`79fef32bda4dd599ea973e790b09e58ed02dd9b1` (tree
`645b468916ddb3c4437a96151c6740ab08d9f646`) completed 127 related
RED-to-GREEN tests; `compileall` and diff checks passed. Earlier
head `f8783af9` completed 244 related tests with warnings treated as errors and
Ruff. The full local collection is not claimed: its environment lacks the
native `fast_mlsirm` module and NumPy, while unrelated stale tests still import
the removed `_DEFAULT_EMBEDDING_CLAIM_LEASE_SECONDS` symbol and deprecated
`jsonschema.RefResolver` fails under warnings-as-errors.

Status remains **Proposed**. Protected exact-head Checks, independent review,
ordinary merge, immutable owner release, and consumer pin are still required.
Leaf #2281 has repaired DOCX relationship order but still needs HWPX
relationship-order and source-position provenance; the owner fix does not
complete or bypass that leaf work.

## 2026-09-08 item-covariate two-group boundary repair (proposed)

Review of PR #1104 at `78d331451c2e9667e949d1d274dfe48708782fa9`
identified a mismatch between the positive-count contract and the two-group
covariate design. One observation reached the native fitter with only group
zero and a two-row covariate matrix; the new boundary test reproduced its
matrix-shape error (one failed test, 33 deselected). The caller now rejects
counts below two before fitting. This structural minimum does not establish
statistical power or measurement validity. Tests verify both group IDs at
counts two, three, and forty, reject zero and negative counts, and independently
pin the harness declaration to 1,200. Boundary and ADR checks passed: 37 tests
in 17.14 seconds. Expanded routing, full-size synthetic report, boundary,
and ADR regression passed: 72 tests in 883.69 seconds (exit zero).
ADR 0053 remains Proposed; production defaults remain unchanged.

## 2026-09-08 declared item-covariate sample size (proposed)

Successor of the held-out bootstrap-coverage slice removes hidden
`ITEM_COVARIATE_SAMPLE_SIZE = 1_200` from
`scripts/benchmark_psychometric_heldout.py`. Sample size is a required
integer declaration of at least two. Missing, boolean, or smaller values fail
closed. The harness run still writes 1,200 as this run's choice and records
`sample_size`. ADR 0053 is Proposed.

Local contract tests on this working tree: item-covariate sample-size
declaration and population checks plus existing held-out key/report pins.
This is not buyer-held-out accuracy, p95 latency, or protected merge
evidence. Production route/conduct defaults stay locked. Other harness
sample sizes remain later work.

## 2026-09-13 NIM consumed-response repair — Proposed

Source `dda57de36dcbd9254f2e4215279494fbaccfc03f` closes HTTP errors consumed
into benchmark outcomes while preserving classification and caller ownership
of propagated errors. Two explicit RED cases become passing; the module's
strict suite passes 137 tests. Combined strict checks remain 239 passed and
1 failed because the separate ModelClient closure owner (#1140) is not yet
integrated. No observed customer KPI gain is claimed. Exact evidence and
limitations are in the NIM benchmark doctoring record.

Follow-up source `7ff2c8e7` generalizes cleanup protection to Exception after
RuntimeError reproduced outcome masking at RED `f67db9c2`. BaseException is
not caught. This repairs primary-outcome integrity, not an observed KPI gain;
the inherited #1140 dependency and prior combined failure remain unresolved.

## 2026-09-09 Rejected observation integrity (proposed)

PR #1109 is stacked on numerical-routing owner PR #1067. At candidate
`181e6d4d`, rejected new/replacement observations preserve retained response
records, vectors, context order, and revision. RED `b335bfa7` reproduced both
mutations; fix `5a4c0e66` passed both regressions. The focused observation and
vector suite at `181e6d4d` passed 10 tests (24 deselected, 41.34s).
The [root-cause runbook](psychometric_observation_atomicity.md) describes shared
callers and limits. This closes two local integrity failures, not customer
accuracy/latency KPIs. Full regression, independent review, protected merge,
and immutable release remain unverified; production defaults are unchanged.

Follow-up `89d8ed51` rejects fractional IRT row values instead of silently
truncating them. The 13-case boundary suite passed in 2.05s and 10 neighboring
tests passed in 3.51s. Integer-protocol inputs remain supported; floats including
`0.0`/`1.0` and numeric strings are no longer valid row values. Accepted-flag
coercion is a separate unchanged limitation. Earlier head `4cc0bf2c` completed
57 local psychometric regressions and 3595 hosted full-suite tests, but those
receipts are not current-code verification after this follow-up. New review and
hosted checks remain required. No customer KPI gain is claimed.

## 2026-09-08 declared judge-effect sample size (proposed)

Successor of the reliability sample-size slice removes hidden
`JUDGE_SAMPLE_SIZE = 1_000` from
`scripts/benchmark_psychometric_heldout.py`. Sample size is a required
positive integer declaration. Missing, boolean, or non-positive values fail
closed. The harness run still writes 1,000 as this run's choice and records
`sample_size`. ADR 0052 is Proposed.

Local contract tests on this working tree: judge sample-size declaration and
population checks plus existing held-out key/report pins. This is not
buyer-held-out accuracy, p95 latency, or protected merge evidence. Production
route/conduct defaults stay locked. Other harness sample sizes remain later
work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-08 declared score-reliability sample size (proposed)

Successor of the DIF sample-size slice removes hidden
`RELIABILITY_SAMPLE_SIZE = 1_200` from
`scripts/benchmark_psychometric_heldout.py`. Sample size is a required
positive integer declaration. Missing, boolean, or non-positive values fail
closed. The harness run still writes 1,200 as this run's choice and records
`sample_size_per_case`. ADR 0051 is Proposed.

Local contract tests on this working tree: reliability sample-size
declaration and population checks plus existing held-out key/report pins.
This is not buyer-held-out accuracy, p95 latency, or protected merge
evidence. Production route/conduct defaults stay locked. Other harness
sample sizes remain later work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-08 declared candidate-group DIF sample size (proposed)

Successor of the assignment-trial slice removes hidden `DIF_SAMPLE_SIZE = 4_000`
from `scripts/benchmark_psychometric_heldout.py`. Sample size is a required
even positive integer declaration. Missing, boolean, non-positive, or odd
values fail closed. The harness run still writes 4,000 as this run's choice
and records `sample_size`. ADR 0050 is Proposed.

Local contract tests on this working tree: DIF sample-size declaration and
population checks plus existing held-out key/report pins. This is not
buyer-held-out accuracy, p95 latency, or protected merge evidence. Production
route/conduct defaults stay locked. Other harness sample sizes remain later
work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-08 declared assignment-design trial count (proposed)

Successor of the held-out context-population slice removes hidden
`ASSIGNMENT_TRIALS = 24_000` from
`scripts/benchmark_psychometric_heldout.py`. Trial count is a required
positive integer declaration. Missing, boolean, or non-positive values fail
closed. The harness run still writes 24,000 as this run's choice and records
`trials`. ADR 0049 is Proposed.

Local contract tests on this working tree: assignment trial-count declaration
and loop-count checks plus existing held-out key/report pins. This is not
buyer-held-out accuracy, p95 latency, or protected merge evidence. Production
route/conduct defaults stay locked. Other harness sample sizes remain later
work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-08 declared held-out context population (proposed)

Successor of the latency-repetition slice removes hidden `TRAIN_CONTEXTS = 24`
from evidence construction, quality evaluation, and paired timings in
`scripts/benchmark_psychometric_heldout.py`. Context count is a required
positive integer declaration. Missing, boolean, or non-positive values fail
closed. The harness run still writes 24 as this run's choice and records
`contexts_held_out` / `contexts_train`. ADR 0048 is Proposed.

Local contract tests on this working tree: context-count declaration and
loop-count checks plus existing held-out key/report pins. This is not
buyer-held-out accuracy, p95 latency, or protected merge evidence. Production
route/conduct defaults stay locked. Other harness sample sizes remain later
work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-08 declared held-out latency repetitions (proposed)

Successor of the sequential-drift horizon slice removes hidden
`LATENCY_REPETITIONS = 200` from
`scripts/benchmark_psychometric_heldout.py`. Per-context timing repetitions
are a required positive integer declaration. Missing, boolean, or
non-positive values fail closed. The harness run still writes 200 as this
run's choice and records `latency_repetitions_per_context`. ADR 0047 is
Proposed.

Local contract tests on this working tree: latency declaration and loop-count
checks plus existing held-out key/report pins. This is not buyer-held-out
accuracy, p95 latency, or protected merge evidence. Production route/conduct
defaults stay locked. Other harness sample sizes remain later work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-08 sequential-drift integration correction (proposed)

PR #1095 source `74c27e7ea5ef3d34593ae55978df8fa520e82334` treated
eight censored non-detections as eight ten-observation detections. A focused
regression reproduced the false median (one failure). The repair separates
censoring counts and horizon from detected-only quantiles, retains failure
denominators, and returns null candidates with complete calibration evidence
when no threshold is eligible. Required horizon/coverage declarations remain.
Twenty boundary tests passed in 17.22 seconds. This is unit-fixture evidence,
not a buyer delay estimate, protected merge, or release. ADR 0046 remains
Proposed; unconditional survival inference and real held-out validity remain open.

## 2026-09-08 declared sequential-drift horizon and censored delays (proposed)

Successor of the coverage-neutral interval-key slice removes the hidden
CUSUM 500/250/100 screen and the abort-on-no-alarm from
`scripts/benchmark_psychometric_heldout.py`. Replications, horizon,
change-point, and exclusive-unit-interval coverage are required
declarations. A replication that never alarms is right-censored at
`horizon - change_after` and counted as a missed detection. The Wilson
upper bound uses the declared coverage and is stored as
`false_alarm_rate_upper_bound`. The harness run still writes 500, 250, 100,
and 0.95 as this run's choices. ADR 0046 is Proposed.

Local contract tests on this working tree: sequential-drift declaration and
censoring checks plus existing held-out key/report pins. This is not
buyer-held-out accuracy, p95 latency, or protected merge evidence.
Production route/conduct defaults stay locked. Other harness sample sizes
remain later work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-07 held-out coverage-neutral interval keys (proposed)

Successor of the declared held-out bootstrap slice renames nested JSON
fields that embedded 95 (`delta_ci95`, `paired_delta_ci95`,
`query_delta_ci95`, `accuracy_delta_ci95`, `heldout_paired_delta_ci95`) to
`*_interval`. Declared coverage remains `bootstrap_confidence_level`. IRT
`interval_95_coverage_rate` diagnostics are unchanged. ADR 0045 is Proposed.

Local contract tests on this working tree: source-key and adaptive-calibration
key checks plus existing declaration/boundary tests. This is not buyer-held-out
accuracy, p95 latency, or protected merge evidence. Production route/conduct
defaults stay locked. Other harness sample sizes remain later work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.
## 2026-09-07 declared held-out bootstrap coverage (proposed)

Successor of the declared workflow-budget slice removes hidden
`BOOTSTRAP_SAMPLES = 2_000` and the baked-in 95% percentile from
