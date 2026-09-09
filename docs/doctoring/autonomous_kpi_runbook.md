# Autonomous KPI experiment runbook

## Stacked quality-trigger repair

Lineage correction: existing PR #1066 at
`59a8f4eadfe0e0dcc5ff47cf1acfb80403e241ad` already owns the complete trigger
repair, including Ready/closed admission and PR-only cancellation. The partial
repair below duplicated its base-filter change. Integrate that branch normally,
retain its complete workflow and tests, and consolidate the extra path-filter
and event-permission assertions into `tests/test_repository_security_metadata.py`.
The duplicate `tests/test_stacked_quality_workflow.py` is removed only after those
assertions are preserved. Run the canonical metadata tests plus the NIM workflow
contracts and actionlint. Neither #1066 nor its predecessor #1060 is closed by
this integration; protected delivery is still required. Historical commands and
results below remain attached to their original revisions.

On 2026-09-09, PR #1108 at `fbb933cbcaa1f1695c6cc305657f450f22b3be4c`
had zero GitHub check runs despite a completed local suite (3,399 passed,
2 skipped). Its base was `autoresearch/20260909-kpi-loop`, excluded by the
repository quality workflow's `pull_request.branches: [main]` filter.
Commit `1a510faa` removes that filter, preserves permissions, and uses the
workflow/repository/PR cancellation key. Central required workflows remain
separate owners; this change cannot provide their approval.

Reproduce with `.venv/bin/python -m pytest tests/test_stacked_quality_workflow.py -q`.
The old trigger fails its assertion; with the repair, this and the existing NIM
workflow contracts pass (9 tests). `actionlint .github/workflows/security.yml`
has no findings. An initial PyYAML-based test failed collection because that
package is absent; the retained stdlib contract needs no new dependency.
The integrated rollback head `c11df645865062da6c4d1680a285eb5c21a91594`
passed 30 persistence/workflow contracts in 8.71 seconds before push.
Do not assign the earlier full-suite count to this new head. After pushing a
new synchronize event, inspect the live run's head and checked-out merge parents;
no run or a queued run is not a pass. Retain both sides of gap-baseline merge
conflicts so rollback evidence and newer research evidence are not discarded.

Status: measurement preparation; no measured customer gain. Owner: CO for
request timing and delivered outcomes; fast-mlsirm for numerical estimators.

## Start and evidence boundaries

### Completed observation-integrity verification

PR #1109 code head `4cc0bf2c92181cb5ea175a1f1e1db1c8a85799bc` completed
the three-file local psychometric regression command with **57 passed in
1159.23s**, exit 0 (Python 3.13.14, fast-mlsirm 0.9.1). Process sampling during
the run found Rust CAT/EAP reduction and thread joins on a heavily loaded host;
this elapsed time is not routing-decision latency.
Hosted job [102339210701](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34311594936/job/102339210701)
completed full pytest with **3595 passed, 2 skipped in 791.75s**. Its tested
merge `75d08ce905dc3d0c0468420bf4094a4cc7359ab3` has parents
`84a6052369a7bf8b6faae5db475bb68a5ad54a91` and the code head above.
These receipts supersede earlier pending-test observations, not the outstanding
independent GitHub approval, protected-owner integration, or release gates.

### Multimodal cost evidence boundary

At CO `632831de9cc2a510af41981711eedc13e38df479`, inspected MMR-Bench v1's
abstract, Section 3.1, and Appendix C.2–C.3; this is a partial read.
The [primary source](https://arxiv.org/html/2601.17814v1) defines a text/image
routing problem. Its normalized cost compares models within a fixed pool;
Appendix C.3 also describes disabled reasoning traces for selected models.
Therefore the reported roughly 33% cost scenario is not a CO invoice saving,
decision-latency p95, or audio/video validation result. CO's model-group
specification cites this paper for evaluation design, not achieved performance.
Any local comparison must fix the candidate and reasoning-policy revisions,
report real prices and latency separately, and retain failed requests. No
production routing or reasoning policy was changed from this partial review.

### Executable reference inventory check

At `9a9f1ab2`, run `python -m pytest tests/test_paper_contracts.py -k
explicit_arxiv -q` in a Git checkout with the project test dependencies.
Result: 1 passed, 4 deselected in 16.76s. An in-memory negative check removed
`2601.17814` only from the inventory read; the test failed with that identifier
and its source path as expected. No source file was modified by that check.
The test uses tracked `.py`, `.rs`, `.md`, and `.toml` text and explicit arXiv
identifiers. It detects discovery omissions, not title accuracy, version/license
compliance, evidence quality, full-paper review, or DOI-only references.

### Expanded-population validity proposal

Source inspection at CO `479bfe7e096832e1711c4d99b59621a66c3a2f59`:
Kim and Chung (2019), ETS RM-19-07, abstract and printed pages 1–8.
Their method checks item DIF and subgroup score-linking invariance separately;
the report does not establish LLM routing performance. See the
[source and APA reference](../papers/README.md#apa-7th-edition-references).

Engineering proposal, not an implemented or validated estimator: treat a new
language, task domain, or model revision as an explicitly declared evaluation
population. CO records those evaluation conditions and observed outcomes;
fast-mlsirm owns estimation, alignment, and diagnostic computation. A released
owner contract should return the reference population, anchor-set revision,
identification constraints, supported strata, uncertainty, and diagnostic status.
Do not equate raw accuracy differences with DIF, or a nonsignificant diagnostic
with proven equivalence. Missing support is unknown, not a passing result.

For acceptance, report held-out correctness and failure denominators by declared
stratum alongside the overall paired accuracy change. Estimate the cost of
retrieving a versioned diagnostic with the same accepted-request-to-durable-
decision clock; do not silently omit it from latency. Offline estimation may
keep the request path small, but requires provenance and an expiry policy whose
operational effect is tested. No new heuristic weights or production default
change follows from this proposal. The next evidence gate is an owner-contract
inventory and an observed-data evaluation design, not implementation copied
into CO. No numerical effect or universal DIF cutoff is claimed.

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

## Isolated verification evidence, 2026-09-09 (PR #1109)

Loop HEAD `8839bfc5f3e6608e11faf3c8a2b237d5bd4050a5` is in sync with
`origin/autoresearch/20260909-kpi-loop`; code diff since
`origin/main` remains `benchmark_priors.py` only, while `tests/`
additionally carries the concurrent session's `test_paper_contracts.py`
guard (+24), which this turn does not claim as its evidence. Open-PR recount is 88
(baseline 85; +1 new draft #1109 on the psychometric stack).

PR #1109 head `4cc0bf2c` verified in isolated worktree
`/tmp/co-verify-1109` (primary checkout untouched):
`tests/test_psychometric_observation_atomicity.py` 6 passed in 52.15s,
exit 0. The `observe_context_id` change validates the copied vector and
complete dichotomous response row before any retained-state mutation
under the existing lock; no new numerical arithmetic is introduced, so
the Rust-authoritative computation rule is unaffected. Hosted checks at
observation time: CodeQL success; `Tests and package quality` and
`Property and coverage-guided fuzzing` still in progress. PR #1108 head
reports no check runs while `dirty` against the loop branch; PR #1094
remains `mergeable: true` but `mergeStateStatus: blocked` on main
protection. No merge, readiness flip, or push to another session's
branch was attempted. Unit evidence only; full regression, independent
review, protected merge, and release remain pending. Worktree removal
follows the docs commit.

## Isolated verification evidence, 2026-09-09 (PR #1109 new head)

PR #1109 flipped from Draft to Ready during the loop and its head moved
`4cc0bf2c` to `b8d2651d61f1d178971997c3ee49e404580fc2aa`, so the prior
6-pass verification is superseded for the new head. Isolated worktree
`/tmp/co-verify-1109b` (primary checkout untouched):
`tests/test_psychometric_observation_atomicity.py` 19 passed in 13.68s,
exit 0. The new delta replaces `int(value)` with `operator.index(value)`
(`operator` was already imported): fractional rows (`0.7`, `1.7`,
`-0.7`), whole-valued floats (`0.0`, `1.0`), and numeric strings
(`"1"`) are now rejected with `TypeError` instead of silently truncated
to `0`/`1`, while the integer protocol (`int`, `numpy.int64`, bools via
`__index__`) is preserved and covered by
`test_integer_protocol_rows_preserve_binary_values`. Direction is
fail-closed evidence integrity: a fractional row was never a valid
dichotomous observation, so refusing it repairs masking rather than
regressing a contract; the compatibility boundary is documented on the
PR. Hosted checks on the new head: both CodeQL jobs success; `Tests and
package quality` and `Property and coverage-guided fuzzing` still in
progress; no reviews posted. No merge, readiness change, or push to the
owner stack was attempted. Unit evidence only.

## Re-observation, 2026-09-09 (PR #1109 same head, PR #1108 unknown)

Loop HEAD `9e08f1448f23a22d10c99f3899021d241910f636` is in sync with
`origin/autoresearch/20260909-kpi-loop`. PR #1109 head is unchanged
(`b8d2651d`), so the 19-pass isolated verification stands without
rerun. Hosted movement since last observation: `Property and
coverage-guided fuzzing` moved from in-progress to success; `Tests and
package quality` remains in progress; still no reviews; state remains
`unstable`, so the merge bar is still unmet and nothing was merged,
flipped, or pushed across branches. PR #1108 reports
`mergeable: null` / `mergeable_state: unknown` (GitHub recomputing the
dirty computation); still not actionable from this loop. Open-PR
recount 88 (baseline 85).
