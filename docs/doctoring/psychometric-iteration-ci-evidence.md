# Solver iteration diagnostic versus numerical acceptance

## 2026-09-08 fixed-horizon drift non-detections

On `6765929f`, a unit-only stream with no alarm reproduced an AssertionError
that discarded valid non-detection outcomes. The harness now records false
alarms, post-change detections, and non-detections with the 250-observation
horizon. Delay quantiles describe detected cases only and are null when none
detect; the conditional detection rate is null when every trial false-alarms.
All calibration results survive even when no threshold is eligible, in which
case candidate fields are null and synthetic acceptance is false.

The former requirement that every trial alarm is preserved as a conservative
candidate-eligibility condition, not an abort. It is not a new validated
operational detection target or a survival-analysis estimate. Four focused
tests passed in 17.76 seconds, covering all non-detections, all false alarms,
mixed detections, and unchanged seeded reference results. Numerical estimation
ownership and live routing defaults are unchanged.

## 2026-09-08 request evidence regression repair

Starting from PR #1067 `ec1c4e66512615ea1f00fa044f3bfba787aab567`, a non-ASCII
policy fixture reproduced one failure in the independent policy-hash assertion.
The test used unescaped JSON while the runtime receipt uses escaped JSON.
The repair matches that serialization contract without changing runtime hashing
and exercises five request entry points with non-ASCII policy content.
Two related review repairs compare the complete starting policy rather than a
hard-coded default and prove a current candidate's observations survive retention
before the candidate pool is emptied. This prevents a stale invented candidate
ID from making the deletion regression pass for the wrong reason.

Focused execution: 8 passed, 64 deselected in 34.73 seconds; `git diff --check`
passed. The separate 72-test execution was still running at this receipt;
no full-suite, hosted acceptance, parameter-accuracy improvement, or protected
merge is claimed. These fixtures are unit-only and contact no live provider.

At parent PR #1067 head a4f693c4, hosted run
[34032452587](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34032452587/job/101484386171)
reported 1 failed, 3581 passed and 2 skipped in 799.59 seconds. The sole failing
assertion required exactly 941 item-covariate solver iterations; the runner
reported 944. Earlier estimate, true-parameter error and convergence assertions
in the same test passed. The differing numerical/OS backend cause has not been
independently isolated; this is not labelled a random CI flake.

At e889e684, the fitting configuration and report share the existing 1000-step
budget. The test requires an integer positive iteration count within that
budget, with the previous converged status and numerical estimate/error checks
unchanged. Iterations remain reported, not overwritten with a portable constant.
The 32 psychometric-routing tests passed in 16.79 seconds. This does not prove
new buyer accuracy/latency or replace full-suite and current-head hosted checks.

Python CodeQL compatibility job 101489554208 in run 34032452544 reports a
successful dispatch with pending verdict and exits 1 until the dispatch workflow
rechecks it. This is not a code finding or a passing security result. Other
language-shard causes were not inferred from the Python shard.

A fresh visual attempt found the Mac locked; no new screenshot is claimed.
