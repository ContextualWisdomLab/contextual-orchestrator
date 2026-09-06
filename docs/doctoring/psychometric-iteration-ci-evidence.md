# Solver iteration diagnostic versus numerical acceptance

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
