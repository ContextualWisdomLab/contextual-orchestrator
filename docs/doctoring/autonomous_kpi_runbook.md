# Autonomous KPI experiment runbook

Status: measurement preparation; no measured customer gain. Owner: CO for
request timing and delivered outcomes; fast-mlsirm for numerical estimators.

## Start and evidence boundaries

### Paper inventory consistency check, 2026-09-09

At `b031d3acecc89b29b35fdd769598aa3826615553`, the paper inventory correctly
marked redistribution permission as unverified but its closing paragraph still
claimed the arXiv non-exclusive license authorized redistribution. The
[official license guidance](https://info.arxiv.org/help/license/index.html)
was rechecked: that license grants limited distribution rights to arXiv, not a
general reuse grant. Commit `34bf2f3f5925a84630edfccaf608e06f5e3192ae` removes
the contradictory assurance and places batch references under their own heading.
All five stored PDF hashes still verify; no PDF was added, removed, or republished.
Actual browser inspection of this revision was attempted but the native browser
tool reported the Mac locked and automatic unlock unavailable. Rendering is
**not visually verified**; inspect the headings and license callout after unlock.

Read AGENTS.md, CLAUDE.md, and the targets in `docs/analytics_spec.md`.
Record head/base, clean or unrelated worktree changes, locked dependencies,
runtime version, dataset identity and permitted use, workload, observation
window, sampling design, resource budget, and failure counts before comparison.
Never replace missing observations with zero or a synthetic oracle score.
Keep experiment results with the tested commit, command, output artifact,
baseline/candidate estimates, uncertainty, and keep/discard decision.

The reviewed CO measurement owner is PR #1067. At
`84a6052369a7bf8b6faae5db475bb68a5ad54a91`, this command runs focused unit
regressions, not a customer performance benchmark:

```sh
uv run --frozen pytest tests/test_psychometric_routing.py tests/test_psychometric_benchmark_boundaries.py -q
```

Its held-out harness uses known synthetic probabilities and numerical fixtures.
Do not use its output to satisfy the observed-customer accuracy target. A
production interval measuring accepted request through durable decision is
required separately. Current observed-data baseline and that interval's measured
p95 remain unverified; no executable end-to-end customer KPI command is claimed.

## Long-running numerical tests

On 2026-09-09, the command above ran in a clean exact-head worktree using
Python 3.14 and installed fast-mlsirm 0.9.1. Process sampling found Rust
`cat_next_item` / EAP CPU reduction, including worker joins. The host reported
10 logical CPUs and approximately 60 one-minute load average. This is evidence
of a busy host, not a measured algorithmic regression or proof of deadlock.
The same execution subsequently completed: **51 passed in 744.99 seconds**,
exit 0. No restart was needed. This duration is host-contended unit execution,
not routing-decision p95 or a baseline suitable for claiming a speedup. For
future runs, reuse the live execution handle, inspect process progress, and do
not restart merely because an observation call yields without output.

The owner source at `256470c7d1df4910a018841499a74d88b751a774` creates a scoped
CPU worker even for one person in `score_eap_cpu_reduce`. This is an optimization
hypothesis only: match installed artifact to source and measure before changing
it. Do not terminate unrelated host jobs or shrink the fixture to manufacture a
speedup. Use paired/interleaved baseline and candidate measurements with recorded
host conditions; retain unfavorable runs and report interference.

## Owner unit experiment receipt, 2026-09-09

Baseline owner `256470c7d1df4910a018841499a74d88b751a774` completed the
scoring-filtered Cargo command with 41 passed, 1 ignored, 1106 filtered out,
exit 0. Compilation took 27m20s; tests took 0.05s. Neither duration is a
customer latency measurement. Candidate code
`b1709fa1e67a70274126d358506c7e9282fe5605` subsequently completed with exit 0.
A post-completion rerun retained the full local log at
`/tmp/co_candidate_scoring_completed.log`: 42 passed, 1 ignored, 1106 filtered
out, 0 failed, test duration 0.39s. The additional single-person parity test
passed. This is the scoring filter, not the complete crate suite or GPU testing.

A separately linked unit probe compared three synthetic missingness patterns
across both built libraries. All four output families matched bitwise, with
single-person versus repeated-person equality also checked. Across 300 calls
per version, baseline/candidate median was 569333/180209 ns and nearest-rank
p95 was 7738375/20093625 ns. The worse candidate tail prevents acceptance;
sequential, host-contended unit timings do not prove a causal regression either.
Owner experiment record: `docs/single_person_scoring_experiment.md` at local
commit `e3d9a939` in fast-mlsirm. No release or CO dependency change occurred.

## Document visual inspection, 2026-09-09

Inspected the actual Edge-rendered `docs/analytics_spec.md` at
`dccd37e032f74251e3c02e38046dab68c0049787`, fragment
`autonomous-experiment-targets`, in English document content with Korean browser
chrome. Browser-tab selection timed out, but native app selection of the
already-created CO KPI tab worked. Opened the screenshot directly in the
inspection conversation: all three table columns, wrapped text, caveats, and
the runbook link were legible without overlap; the heading permalink displayed
visible focus. This is a partial desktop document inspection, not admin-product
UI acceptance. Viewport dimensions, durable image export, responsive sizes,
other locales, and error/loading states remain unverified. Do not mark the
full visual-inspection requirement complete from this receipt.

## Break release cycles without copying implementation

Minimum contract → owner RED test → owner implementation → exact-SHA/digest
isolated real integration → protected immutable release → consumer adoption.

CO can implement its timing/outcome port against test doubles while numerical
owner work proceeds. Doubles prove boundary behavior only. Candidate artifacts
are allowed in isolated CI, never as production dependencies or release proof.
Remove the temporary candidate integration after released-contract adoption;
restore the previous released contract if integration fails. Required reviews,
security checks, and `orchestrator/free` remain enforced throughout.

## Coverage-gate evidence 2026-09-09 (autoresearch experiment 1: discard)

Head `74efc7bf` (code+tests identical to `origin/main@414f2297`), coverage
7.15.0, exact issue-#1075 gate block on unmodified code: 134 passed in
143.50s, `nim_benchmark.py` 1205/0/436/0 = 100%, `--fail-under=100` exit 0.
Former gaps 434 / 645 / 671->682 are covered by later-main acceptance tests;
no change needed. Single-file `tests/test_nim_benchmark.py` alone is 93% —
always run the full three-file gate before claiming coverage. Unit evidence
only, not customer accuracy.

## Shared primary checkout (lesson 2026-09-09)

The primary checkout may receive commits from a concurrent scheduled session
mid-run (7 docs-only commits observed on the loop branch via reflog; purposes
legible, code+tests untouched). Before and after long runs, record
`git rev-parse HEAD` and `git diff --stat origin/main...HEAD --
contextual_orchestrator/ tests/`; docs-only drift does not invalidate code
evidence, but any code/test drift does. Prefer isolated worktrees for code
experiments; never rebase or push another session's branch.

## Autonomous KPI scope, 2026-09-09 (selected without asking)

Goal: USD 20,000,000,000 sale quality and customer-felt gap closure.
Scope is chosen under `docs/analytics_spec.md`; no KPI-scope question was
asked. Primary engineering metric is `open_pr_count` (lower is better,
`gh pr list --state open --json number | jq length`): 85 at loop start,
87 on recount (concurrent-session growth, not this change). PR 0 only via
merge or verified-successor full-delta inheritance; no force-push and no
close without evidence (user-explicit, no valid delta, malicious change,
or verified complete inheritance only).

Product acceptance stays observed-only: delivered-correct fraction at
least +1 point with the 95% difference interval wholly above zero, and
routing-decision p95 at most 20 ms with at least 10% reduction and the
95% candidate/baseline ratio interval wholly below 1, each with declared
population, workload, failure denominators, and uncertainty. Synthetic
true-parameter recovery is unit evidence only (family-wise aligned RMSE,
no regression); never substitute it for buyer accuracy. Latency claims
use accepted-request to durable-decision timestamps on one monotonic
clock, including queueing, selection, and persistence; worker durations
that include generation cannot supply this metric. Measured-local
commercial signals (`commercial_readiness_pass_rate`,
`buyer_evidence_completeness`, `security_control_pass_rate`,
`trace_audit_completeness`) may advance; buyer/production warnings stay
warnings until buyer or production evidence arrives.

## Isolated verification evidence, 2026-09-09

Head `0ea2a58d34fb07e15c12dfcfd65f7242b2a45c91`, base
`origin/main`; `contextual_orchestrator/ tests/` diff since `origin/main`
is `benchmark_priors.py` only (17 insertions, 20 deletions, docstrings
and comments bounding the legacy heuristic; runtime unchanged).
`tests/test_model_group.py` plus `tests/test_benchmark_priors.py`: 37
passed in 25.82s, exit 0, on the primary checkout.

PR #1108 head `4316be85` verified in isolated worktree
`/tmp/co-verify-1108` (primary checkout untouched):
`tests/test_persistence.py` 20 passed in 32.42s, exit 0. The
`_save_sync` change uses the SQLite connection context under the writer
lock so a failed keyed replacement rolls back instead of leaking its
DELETE into the next commit; the added test covers insert-phase and
deferred-commit-phase failures, closed-transaction state, and reopened
persistence. Focused unit evidence only; no customer KPI, full-suite,
release, or deployment claim. Merge test of loop HEAD `0ea2a58d` into
PR #1108 auto-merged code but conflicted in
`docs/product-technical-gap-baseline.md` (both sides append); restack is
a normal merge with manual docs resolution by the PR owner, never a
force-push. Worktrees removed after verification.
