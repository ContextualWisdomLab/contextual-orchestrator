Warning: truncated output (original token count: 136633)
Total output lines: 7208

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
RED-to-GREEN tests; `compileall` and diff checks passed. Current exact head
`d4c1065720d8efc87b7f146c7318c6f1cf36265e` (tree
`c5b95492b251f397b514801d0d14b1217e2569a1`) additionally removes the two
stale collection blockers, preserves null as an unbounded provider-batch wait,
and closes the touched loopback listeners after shutdown. Those focused lanes
completed 97 tests with warnings treated as errors; compileall and diff checks
passed. Earlier
head `f8783af9` completed 244 related tests with warnings treated as errors and
Ruff. The full local collection is not claimed: a provider-key-free fail-fast
run reached 856 passed / 1 skipped before exposing another stale completions
listener cleanup, which was repaired and then passed its 4-test file; the
borrowed verifier also lacks the configured asyncio plugin.

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
`scripts/benchmark_psychometric_heldout.py`. Resample count, exclusive-unit-interval
coverage, and seed are required declarations. Missing, boolean, non-positive,
or non-representable declarations fail closed. The script entry and full
harness tests pass 2,000, 0.95, and seed 568 as this run's choices. ADR 0044
is Proposed.

Local contract tests on this working tree: 19 related declaration and
boundary tests passed. This is not buyer-held-out accuracy, p95 latency, or
protected merge evidence. Production route/conduct defaults stay locked.
Nested interval key names are the successor slice. Other harness sample
sizes remain later work. Parent
[#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-07 declared paired-bootstrap coverage (proposed)

Child successor of [#1074](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1074)
removes the hidden 2,000-resample 95% interval and the baked-in
`conduct_bounded` / `route_once` / cheapest / hindsight comparison subset from
`contextual_orchestrator/nim_benchmark.py`. Resample count, exclusive-unit-interval
coverage, seed, and policy pairs are required declarations. Missing, boolean,
non-positive, non-finite, empty, duplicate, or degenerate declarations fail
closed. The percentile method name no longer embeds 95. Report schema 4.0.0
records the declarations in provenance. The workflow and CLI must pass them
explicitly; 2,000 and 0.95 in those files are run declarations, not code
defaults.

Local three-file coverage on this working tree: NIM statements/branches 100%,
interrogate 100%, 175 related tests passed. This is not buyer-held-out
accuracy, p95 latency, or protected merge evidence. Production route/conduct
defaults stay locked. Token and workflow-depth budgets are the successor
slice. Parent [#1067](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1067)
still needs independent review.

## 2026-09-07 declared workflow depth and token budgets (proposed)

Removes hidden `MAX_WORKFLOW_DEPTH = 5` and `DEFAULT_MAX_OUTPUT_TOKENS = 264`
from `contextual_orchestrator/nim_benchmark.py`. Request planning, equal-budget
cells, CLI, and provenance require positive integer declarations. Missing,
boolean, or non-positive values fail closed. The equal cell token budget is
the product of the two declarations. Workflow YAML and tests may still write
5 and 264 as this run's choices. Report schema stays 4.0.0. ADR 0043 is
Proposed.

This is calculation-contract evidence, not buyer-held-out accuracy, p95
latency, or protected merge. Production route/conduct defaults stay locked.

## 2026-09-13 artifact runtime migration — Proposed

Source `7032bee94c85d4937ddad21de88bccd35051ff29` upgrades four artifact
pins to the verified Node 24 action, preserving every upload option and gate.
Actionlint and eight workflow contracts pass locally; hosted publication and
review remain unproven. The central owner still needs a released reusable
contract preserving CO quality, wheel and fuzz requirements before thin-caller
migration. [Evidence and alternatives](doctoring/artifact_runtime_migration.md).
This is operational maintenance, not measured accuracy or decision-latency gain.

## 2026-09-13 Camoufox MCP renderer SDK contract

`privacy_policy_analysis._render_policy_document_with_camoufox` imports the MCP
Python SDK 2.x client API (`mcp.Client`, `streamable_http_client(url,
http_client=...)`), but no document or dependency declaration said so. With a
1.x SDK installed (1.23.3 locally) the import raised an opaque
`cannot import name 'Client'`, `crawl_policy_document` swallowed it into the
static-text fallback, and the pinned-client test crashed with `AttributeError`
instead of skipping (full suite at `012beaac`: 1 failed / 3601 passed /
1 skipped). Candidate `47db9ebf` raises an explicit `ImportError` naming the
`>= 2.0` requirement and the installed version, runs the pinned-client test
through `sys.modules` stubs of the 2.x surface (no SDK needed, import path
covered in CI), and adds a 1.x stub regression test plus both states of the
installed-version helper. Verified: mcp 1.23.3 → 12 passed; 2.x API
introspected from an isolated `mcp==2.2.0` environment.
Not established: a live Camoufox round-trip, and an operator-visible signal when
the fallback is taken (the fallback still swallows `ImportError`/`OSError`).

## 2026-09-13 Trace HTTP fixture successor — Proposed

Candidate `e88562187b7ab3bf681b306ab98d2ca821ae82ed`, based on #1140
`38c0603a`, repairs client error-body and listener ownership in the trace HTTP
tests without changing production authorization or routing. Targeted strict
checks pass (31 trace cases; 126 related cases), and the full default suite
passes 3670 tests with 2 skipped. Full strict remains RED: 1173 failed,
2494 passed, 2 skipped, 13 errors. All process exits were observed.
This closes a test-validation gap, not an observed customer accuracy or latency
gap. Required review, full strict remediation and protected delivery remain.
Ownership, RED evidence, independent review and exact-head logs are in the
[HTTP resource runbook](doctoring/http_test_resource_lifecycle.md#trace-http-fixture-successor-2026-09-13).

## 2026-09-13 Test-owned listener and HTTPError resource warnings

`python -m pytest tests -q -W default` at `012beaac` emitted 2013 warnings,
1221 of them unclosed listening sockets from test `_server()` helpers that call
`shutdown()`/`join()` but never `server_close()`, plus `HTTPError` bodies read
without closing. Production `server.py` already calls `server_close()` after
`serve_forever()`, so this is test hygiene, not a runtime defect. Candidate
`80dedd08` applies an exact-pattern transformation to the 215 test files that
no open PR touches (1055 `server_close()` sites, 210 `with exc:` wraps): the
same command reports 475 warnings with an identical pass/fail set. Remaining
sockets (155) sit in files owned by open PRs #1152/#1140/#1159/#1155/#1149;
unowned sqlite3 handles in `tests/test_cost_ledger.py` and six one-off
`HTTPError` handlers are tracked in #1168 (review 2026-09-20). Aggregate
warning counts are a hygiene KPI, not a latency or accuracy measurement.

## 2026-09-12 SSE test-fixture socket ownership RCA

Draft optimizer PR #1137 exact `341bf003561d6118a38c142c1dc9a131696b1ebf`
and protected `main@012beaacd0631f8cd3391c77744eeb626269b5de` independently
reproduced `tests/test_true_streaming.py::test_stream_send_parses_real_provider_sse`
under `pytest -W error`: `_FakeSSEProvider.__exit__` called
`ThreadingHTTPServer.shutdown()` without closing the listening socket, producing
`ResourceWarning` and `PytestUnraisableExceptionWarning`. The sibling
`_CapturingSSEProvider` had the same lifecycle defect. A standard-library probe
confirmed that `shutdown()` leaves the descriptor open while `server_close()`
changes it to `-1`.

RED `a38258c4b25b3b4994b61d42708aea9ef0292b1d` requires both provider
contexts to leave descriptor `-1`. GREEN
`093d03f9329927a8e9d130a3ff623800bb1f34de` adds only
`server_close()` to the two context-manager exits. This is test-harness resource
ownership, not optimizer behavior or provider routing. It resolves one proven
root warning; it does not classify the other failures in #1137's truncated
full-suite output or convert that Draft's skipped product jobs into passing
evidence. Hosted exact-head checks and independent review remain required.

## 2026-09-13 Served requests had no correlatable identity (#1016, partial)

Gap table for #1016 at `012beaac`: request identity reached error payloads
only (`server.py` error adapters), typed per-attempt outcomes existed only on
the structured synthesis path (`orchestration.route` / `attempts`),
`/v1/provider_readiness` is preflight-only, and no versioned outcome contract
exists. Candidate on `fix/request-id-response-header-1016` closes the first
row: `_send_security_headers` now emits `x-request-id` with the server-generated
identity on every response path. RED: three real HTTP cases (served chat,
401, served stream) failed on a missing header; GREEN after the change, with
`tests/test_stream_error_identity.py` unchanged and passing. Not established:
typed attempt evidence on the single-worker route path, cancellation/deadline
as a typed field, and a published contract version; those rows stay open.

## 2026-09-14 reference-cases terminology cleanup (#1015)

The operator Evaluation surface labeled its dataset class "Golden prompts",
which #1015 identified as a buyer-visible terminology defect: #1014 and
fast-mlsirm #1727 introduced generated, provisional, adjudicated,
adjudicated-but-not-validated, challenged, sampled, and validated-anchor
dataset states, and "golden" wrongly claimed a single, uniform authority
level across all of them. `contextual_orchestrator/admin.py`'s `en`/`ko`
translation bundles rename the `golden_prompts` key to `reference_cases`
("Reference cases" / "참조 평가 사례"), and the Datasets view's mock row and
renderer follow the same key so the rendered copy tracks the translation.
Locale-key parity between `en` and `ko` is preserved and covered by
`tests/test_admin_contract.py::test_reference_cases_terminology_replaces_golden_prompts`,
which also asserts no locale still renders "golden"/"골든" wording. No
external API, transport, database, or export field in this repository used
the name `golden_prompts`, so no compatibility alias was required. This is
presentation-only: provider routing, generation, scoring, adjudication,
validation evidence, and anchor promotion are unchanged. The richer
vocabulary #1015 recommends (`Validated anchors`, `Provisional`,
`Adjudication required`, `No fixed anchors`, etc.) is not yet surfaced
anywhere in the admin UI and remains an open gap for the #1014 dynamic-
evaluation work to wire up.

## 2026-09-14 inference-scoped readiness probe (issue #926)

Local branch adds `GET /v1/readiness`, authorized at `inference` scope, so a
minimal-privilege caller such as `ContextualWisdomLab/.github`'s CI review
sidecar (ADR-0005) can get real per-candidate liveness diagnostics
(`status`, `failure_code`, `latency_ms`) without being provisioned an
admin-scoped token that would widen it to the full `/api/v1/*` operator
surface. `TaskOrchestrator.inference_readiness_report()` reuses
`provider_readiness_report()` — no second probe implementation — and returns
an explicit allowlist (`agent_id`, `model`, `provider_name`, `status`,
`failure_code`, `latency_ms`, and, when present, `rate_limited_until`/
`earliest_ready_seconds`); credentials, base URLs, admin audit fields, and
`usage` are stripped. `?refresh=true` shares the existing
`provider_readiness_report` lock with the admin route; no new rate limit was
invented since none existed to reuse beyond that lock. The existing
admin-scoped `/api/v1/provider_readiness/latest` is unchanged (its contract
test still passes). Local evidence:
`python -m pytest tests/test_inference_readiness_probe.py tests/test_api_contract.py
tests/test_self_check.py tests/test_security_hardening.py
tests/test_provider_reliability.py -q` passes. This is local, single-branch
evidence, not a protected-main merge or hosted CI run; sidecar adoption and a
live gateway round-trip from `.github` remain open.

## 2026-09-13 Response lifecycle repair candidate

Final frozen validation candidate `345ee6b2` passed 275 focused strict tests and
3662 default tests (2 skipped), both exit 0. Its complete strict suite remains
RED: 1188 failed, 2470 passed, 2 skipped, 13 errors, exit 1. Later documentation
receipts do not change the tested source or turn this result into acceptance.

PR #1140's unpublished local candidate `dc88b2f3` closes consumed chat, raw,
binary and synthesis HTTP error responses after classification, and before
retry/backoff where applicable. Caller-owned raw-error handoff remains intact.
Test-owned listeners and SQLite connections are closed at their owning boundary.
The customer-relevant gap is reliable recovery without accumulating abandoned
responses; no live-load resource or decision-latency gain has yet been measured.

At production head `69a5c26b52601832b5faa6ee23a8f7251816038c`, the default
suite passed 3661 tests with 2 skipped (152.37s, exit 0), but strict warnings
produced 1193 failures and 11 errors (2467 passed, 2 skipped; exit 1). These are
not comparable to a different worktree's test population. Test-only follow-up
`dc88b2f3` passed 275 focused strict tests, including synthesis cleanup ordering
and preservation of the final HTTP 413 when cleanup raises. Production review
found no semantic blocker; this does not satisfy remaining hosted gates.

Remaining work: independently reproduce and attribute residual resource roots;
verify complete current-head checks/reviews; finish document visual evidence;
integrate under branch protection and verify release/runtime behavior. Keep this
candidate Proposed and unreleased. No model selection default, psychometric
validity claim or actual accuracy/latency KPI is changed by this repair. See the
[single owner runbook](doctoring/http_test_resource_lifecycle.md) for commands,
exact-head evidence, rejected approaches and visual-inspection limits.

Next separate test-resource gap: the trace HTTP honesty authorization singleton
fails independently at `f598d982` with an unclosed 401 response and listener
(1.85s, exit 1). The test file is unchanged from #1140 remote `eeed2d98`;
latest file history includes `0906ee80`, `1287da2e`, `5f2753ac`. A live inventory
of 95 open PRs returned no matching file. This is bounded ownership evidence,
not a blanket claim that all remaining strict failures are pre-existing. Keep
the source repair outside #1140; its runbook records the exact reproduction.

## 2026-09-07 release verification repair (Proposed, PR #1030)

Source checkpoint: `8443719334d31012d8306dbb517cce6e023443c7`.
The older September 2 narrative below is historical, including its optional
SBOM and manual-owner-dispatch descriptions; it is not the current contract.

The release gate now requires the four actual integrated quality jobs rather
than six retired job names. A test compares this inventory with the current
workflow. Existing SBOM assets must match the verified artifact byte-for-byte;
same-name assets cannot bypass verification and are never overwritten.
Missing, empty, different, or unavailable downloads fail publication.
Real attachment-step execution with a stub GitHub CLI reproduced two false
successes before repair. The 71 focused release checks then passed in 12.11s.
These are software tests, not evidence of an actual published package.

The user authorizes automatic eligible publication. Additional routine human
dispatch approval is not a prerequisite, but protected integration, exact-head
checks and required reviews remain mandatory. This lane still does not publish
to PyPI: the direct-URL fast-mlsirm dependency requires its canonical registry
release first (existing owner PRs #1692 and #1471 in fast-mlsirm).

Remaining acceptance evidence includes a protected release, installed consumer
conformance, and registry artifact provenance. Concurrent asset replacement and
the interval between public Release creation and mandatory-asset attachment
remain separate limitations. Neither local tests nor byte comparison proves
buyer accuracy, routing latency, or complete release-transaction atomicity.

## 2026-09-02 canonical immutable release + resumable long-running execution

Observation time: 2026-09-02 Asia/Seoul.

### The gap, with direct consumer evidence

This repository has never cut a release: `git tag -l` was empty, no
`.github/workflows/*release*.yml` existed, and `GET /repos/
ContextualWisdomLab/contextual-orchestrator/releases/latest` returned 404.
`pyproject.toml` has carried `version = "0.2.0"` and `CHANGELOG.md` an
`## [0.2.0] - Unreleased` section through hundreds of merged PRs, and
`CHANGELOG.md`'s own preamble already stated the intended process — but
nothing had ever executed it.

Four independent downstream consumers hit this wall on
[`contextual-orchestrator#971`](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/971)
(owner seonghobae, all comments dated 2026-09-02 Asia/Seoul):

- **[`ContextualWisdomLab/keyverse#132`](https://github.com/ContextualWisdomLab/keyverse/issues/132)**:
  vendors this repository at commit `045d17da5e2aea56a97e241ee158ab1628d78660`,
  175 commits behind protected `main`; a later comment confirms it is still
  pinning `464da4715b495b5eaaa593eba3796e2d976ee0c9` because "[t]he owner
  repository currently has no GitHub `latest` release endpoint (`/releases/
  latest` returns 404)."
- **`ContextualWisdomLab/bandscope#881`**: told explicitly not to copy the
  mutable owner branch or invent a direct provider fallback while waiting for
  "an immutable contextual-orchestrator release with the compatible
  OpenAI-style gateway/API contract."
- **Wardnet** (consumer-owner handoff comment on `#971`): "[f]resh release
  inventory for `ContextualWisdomLab/contextual-orchestrator` is empty, so
  Wardnet cannot correctly replace these seams with a mutable branch or
  copied source."
- **`ContextualWisdomLab/EgressWeave#235`**: a 45-minute Actions job timeout
  on the same gateway-backed pattern — the resumable-long-running-execution
  half of this gap, tracked here but explicitly out of scope for the release
  mechanism landed below (see Non-goals in ADR 0129).

The owner's stated RED/GREEN acceptance for the release piece, verbatim
(PR #971, comment at 2026-09-02T18:26:04Z): "the resulting released API/
client/schema is immutable enough for consumers to pin without vendoring
this repository's source ... No paid/provider-specific fallback should be
required to consume it."

### Research: does this compose with `release_authorization.py`?

Read in full before designing anything:
`contextual_orchestrator/release_authorization.py`,
`docs/planning/adrs/0020-fail-closed-release-authorization.md`,
`docs/commercial_release_candidate.md`,
`docs/doctoring/release-authorization.md`,
`tests/test_release_authorization.py`,
`tests/test_release_authority_snapshot.py`,
`tests/test_commercial_release_candidate.py`,
`scripts/ci/release_authority_snapshot.py`.

Confirmed by reading the code (not assuming): that machinery is a pure
evaluator (`evaluate_release_authorization`) plus a read-only, **PR-scoped**
collector, feeding exactly one caller —
`/api/v1/commercial_release_candidates/latest`, a buyer-facing product
readiness report behind admin auth inside the running gateway. It is never
invoked by any GitHub Actions workflow today, requires a KV-registered HMAC
signing key before a snapshot can even be loaded, and has no code path that
creates a git tag, a GitHub Release, or any publication artifact —
`docs/commercial_release_candidate.md` says as much itself ("a local product
readiness artifact, not a ... production compliance certificate").

**Conclusion**: a new, distinct concern, not a duplicate. The two do not
compose at the function-call level because `collect_authority()` is
PR-scoped and protected `main`'s tip after a merge is not "a pull request" —
re-deriving "which PR produced this commit" indefinitely into the future
would itself duplicate GitHub's merge bookkeeping inside this repository,
which ADR 0020 already warns against. They share the same fail-closed
spirit without sharing code: branch protection already enforced the checks/
review evidence `evaluate_release_authorization()` would ask for, once, at
merge time — the release gate's job is to confirm a commit really is that
untampered protected-`main` tip, not re-litigate a question branch
protection already answered. Full reasoning:
[ADR 0129](planning/adrs/0129-canonical-immutable-release.md).

### What was built (this session, landed on a branch — not yet merged, no release cut)

- **ADR**: `docs/planning/adrs/0129-canonical-immutable-release.md` — trigger
  (`workflow_dispatch` only, explicit `version` input, never push/schedule),
  gate (exact current-main-tip check, `pyproject.toml` version match, tag-
  non-existence, a fresh full-suite pytest run), release contents (annotated
  tag `vX.Y.Z`, GitHub Release with CHANGELOG-derived notes, best-effort
  CycloneDX SBOM asset), and an explicit non-goals list (no PyPI publish, no
  release-on-every-merge, no automatic version bump, no dynamic ruleset-name
  re-derivation).
- **RED → GREEN, test-first**:
  - `tests/test_release_notes.py` (10 tests) written first against a
    not-yet-existing `scripts/ci/release_notes.py`; confirmed failing
    (`FileNotFoundError`), then `scripts/ci/release_notes.py` implemented
    (pure `read_declared_version`/`extract_changelog_section`/
    `render_release_notes` plus a `main()` CLI) to make all 10 pass. 100%
    interrogate docstring coverage.
  - `tests/test_release_workflow_contract.py` (15 tests) written against
    `.github/workflows/release.yml`; confirmed the file was absent on
    `origin/main` (RED baseline) before implementing the workflow, then all
    15 passed against the new file (GREEN). Follows this repository's
    existing text-assertion contract-test convention (`tests/
    test_nim_benchmark_workflow_contract.py`) rather than adding a new
    PyYAML dependency nothing else in this repository uses.
- **`.github/workflows/release.yml`**: implements the ADR 0129 gate exactly
  as designed above; `permissions: contents: write` is scoped to the release
  job only, every other default stays `contents: read`.
- **`docs/RELEASING.md`**: new, maintainer-facing runbook for dispatching a
  release, its preconditions, and rollback policy (a mistake gets a new
  patch release, never a moved/deleted tag as routine practice).

### Verification evidence

- `python -m pytest tests/test_release_notes.py tests/
  test_release_workflow_contract.py tests/test_planning_adr_identifiers.py -q`
  → 26 passed.
- `python tests/test_self_check.py` → `ok`.
- `python -m interrogate -c pyproject.toml .` → `PASSED (minimum: 100.0%,
  actual: 100.0%)` — this repository's repo-wide docstring gate, unaffected
  by the new `scripts/ci/release_notes.py`.

### Review-driven hardening (same PR, before merge)

Devin Review and CodeRabbit found nine issues (five and four respectively,
three overlapping) against the initial cut above, all fixed on the same
branch before merge:

- **Concurrent-merge staleness**: added a second, authoritative main-tip
  check immediately before tag creation (after the fresh test run and note
  rendering), alongside the original fast-fail early check.
- **least privilege**: split `release.yml` into a read-only,
  credential-less `verify` job (tests, note rendering, SBOM lookup —
  `actions: read` lives here, scoped to just this job) and a write-scoped
  `publish` job (tag + GitHub Release only), so repository-controlled test
  code never runs alongside a write-scoped token.
- **Idempotent retry**: an existing `vX.Y.Z` tag is now resolved via the
  commits API into resume (same commit, unpublished Release — skip
  re-tagging) vs. reject (different commit, or an already-published
  Release), replacing the old any-existing-tag hard fail that stranded a
  half-published release on any post-tag failure.
- **SBOM lookup genuinely non-fatal**: `gh run list`/`gh run download`
  failures are now each guarded by an explicit `if !`, instead of a bare
  `set -e` that aborted the whole job on the `actions: read` permission gap.
- **TOML table-boundary bug**: `read_declared_version` (and the workflow's
  version-match step, via the same tested function) now bounds its search
  to the `[project]` table's own body, so a same-named `version` key under
  an earlier unrelated table can never be mistaken for the real one.
- **`/releases/latest` mutability**: `docs/RELEASING.md` and this ADR's
  Consequences section now correctly describe `/releases/tag/vX.Y.Z` as the
  immutable pin and `/releases/latest` as a mutable discovery alias only.
- **Research grounding**: ADR 0129 gained a section citing SemVer 2.0.0,
  Keep a Changelog 1.1.0, and the GitHub Releases API — the normative
  standards this process tooling implements, not an academic literature
  review.
- Test suite grew to `tests/test_release_notes.py` (13 tests),
  `tests/test_release_workflow_contract.py` (17 tests), and a new
  `tests/test_release_workflow_idempotency_contract.py` (12 tests) asserting
  real step order and job-scoped permissions per job block, not just
  substring presence. `python -m pytest tests -q` → 3390 passed (plus 3
  pre-existing, unrelated failures confirmed present on the unmodified
  branch too); `python -m interrogate -c pyproject.toml .` → 100.0%.
- Full `python -m pytest tests -q` run for regression-freedom before landing
  the PR (see the PR body for the exact pass count from this run).

### Explicitly not done in this session

Per the owner's own instruction: no real release was triggered. Cutting the
first `v0.2.0` tag is a separate, deliberate action left to the repository
owner after this mechanism is reviewed and merged. The resumable-long-
running-execution half of the 2026-09-02 owner comment (EgressWeave#235,
`OPENCODE_RUN_TIMEOUT_SECONDS`, checkpoint/re-dispatch across runner
termination) is unaddressed here — a real, separate runtime gap, deliberately
out of scope for this release-mechanism pass (see ADR 0129's Non-goals).

## 2026-09-13 request-decision export candidate

[PR #1158](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1158)
implements request-scoped milliseconds on export owner #1138 at base
`1881ef06ed90ee72eb7209434db366c851cd68dc`. Source
`45cc666f9fd52aedf6484b345f30857d7f9d72bf` also repairs admission metadata
incorrectly supplying missing final acknowledgement or selection evidence.
This preserves the intent of #1125 without claiming its per-step trace contract
fully inherited; neither predecessor is closed. No new timer or routing policy
is introduced. Focused strict contracts passed 69 tests; default full regression
passed 3,764 with 2 skipped. Isolated noneditable macOS ARM64/Python 3.12 wheels
passed the same 69 strict contracts. These are controlled test results, not an
observed correctness cohort or decision-latency improvement.

Candidate head `0a2626867c0baa6a95ad40f3f00e40008359cca2` has a real
[manual Security run](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34708859235)
whose three jobs were observed running, not completed. Draft PR automatic jobs
were skipped by their explicit Draft condition; that is not secret absence.
Protected review, merge-result verification, publication, ingress-denominator
reconciliation and observed KPI comparison remain open. Actual GitHub
screenshots covered the two changed production files and both changed test
files at 1265 x 712 English without observed clipping or overlap; this is not
the complete product UI/locale matrix. The default full-test log's isolated
request-log fragment remains unresolved: strict standalone telemetry tests
passed 50 in 3.26s without reproducing it. Detailed receipts remain in the
[candidate runbook](https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/0a2626867c0baa6a95ad40f3f00e40008359cca2/docs/doctoring/request_outcome_export_validation.md).

## 2026-09-13 residual diagnostic acceptance gap

Research follow-up `e9d51ac7` identifies an owner-contract requirement: declare
whether uncertainty in estimated response-time residuals is propagated or held
fixed, and fit preprocessing within training partitions. Posterior-predictive
model checks do not establish observed accuracy or decision latency. The
[primary-method intake](doctoring/lart_measurement_review.md#nonparametric-diagnostic-follow-up-2026-09-13)
records the read scope and failed PDF rendering; no estimator or production
policy is changed. Owner implementation and observed evaluation remain open.

## 2026-09-13 Virtual-selector ambiguous-timeout failover (#1166, #1045)

Noema review's org CI calls `POST /v1/chat/completions` with the virtual
model `orchestrator/free`. Sidecar log evidence from run 34754423834 attempt
2 (PR #1166) showed one `provider_attempt_failed ... TimeoutError` on
`nvidia_nim_deepseek_ai_deepseek_v4_pro_0813`, followed by
`circuit_failure` and `request_failed status=502` -- while three other
free-pool candidates admitted by the same preflight were never called. The
`_is_ambiguous_passthrough_transport_failure` fail-closed rule introduced for
#1045 correctly classifies a timeout's outcome as unknown for *the candidate
it happened to*, but `TaskOrchestrator.proxy_completion`'s passthrough
candidate loop applied that same fail-closed decision to the whole *request*
even when the request used a virtual selector with other ready, ranked
candidates still available -- contradicting
`_orchestrated_provider_completion`'s documented behavior that virtual
selectors advance across retryable transport failures (502/429/timeout).

The restack onto current `main` reuses the method's existing
`virtual_selector` flag through the candidate loop's ambiguous-transport
branch: the failing candidate is always recorded as a breaker observation,
but a virtual selector now `continue`s to the next ranked candidate instead
of raising immediately. An explicit concrete model keeps its single-shot,
fail-closed `502 provider_outcome_unknown` path. Exhausting every candidate
under a virtual selector still raises via `classify_provider_failure`.
`tests/test_passthrough_provider_failover.py` covers explicit-model,
`None`/`AUTO_MODEL`, `FREE_MODEL`, and all-candidates-exhausted cases.


## 2026-09-17 context-window candidate filter + overflow failover (#1178/#1174)

`ModelAgent.context_window` is discovered and persisted but was not consulted
during virtual-selector candidate selection. This change adds the pre-flight
lane (skip known-too-small windows via a labeled lower bound; ADR 0133) and
classifies provider 400 context-window overflow as a request-size rejection
for failover without health debit. Unknown windows and explicit concrete
model pins remain unfiltered. Tool-call capability exclusion for #940 remains
on `main` via #1170.

## 2026-09-08 PR #971: unmodeled diversity displacement + full-pool ordering (fail-closed)

Scope is the four-commit chain on branch
`fix/model-group-timeout-openrouter` at exact head `838cbcb7`:
`575148b9` fail-closed ambiguous bootstrap admission,
`50b0c869` equal-price admission boundary cover,
`7206c5f6` reject unmodeled diversity displacement,
`838cbcb7` reject unmodeled full-pool ordering.

`575148b9` `fix(routing): fail closed on ambiguous bootstrap admission`
is the GREEN for the RED already recorded in the `2026-09-07 PR #971:
fail-closed ambiguous bootstrap admission` entry above
(`eeb9cc1bafe579032ab48778fa08c24e0b3f0aa1` RED, Security and Quality
run `34071330949`, job `101589111271`, `2 failed, 3490 passed,
2 skipped`). Referenced here, not re-argued: tied comparable-cost
candidates fail closed with an operator action instead of letting
lexical provider/model identity decide admission.

`50b0c869` `test(routing): cover equal-price admission boundary` is
test-only, no production change. It pins the equal-price tie boundary
so the `575148b9` fail-closed rule has an executable contract on
identical comparable-cost admission.

`7206c5f6` `fix(routing): reject unmodeled diversity displacement` is
the bounded-cutoff fail-closed GREEN. RED: a diversity proposal could
displace a price-evidenced candidate at the cutoff without a modeled
rule. GREEN: compare the diversity proposal against the price-evidenced
sequence and reject unmodeled displacement instead of silently
substituting. No new ranking, weight, quota, provider preference, or
learned-quality claim is added.

`838cbcb7` `test(routing): reject unmodeled full-pool ordering` is
test-only at the exact head, no production change. It pins the
complete-pool reordering boundary fail-closed: `tests/test_model_discovery_boundaries.py`
`+28` and `tests/test_provider_bootstrap.py` `+15`. Unmodeled
full-pool reordering fails closed rather than returning a silently
re-ranked pool.

Local verification on exact head `838cbcb7`:
`tests/test_pr971_review_quality_regressions.py` `4 passed`,
discovery/bootstrap selection `186 passed`,
`interrogate` `100.0%` (`679/679`). `CodeRabbit` `52.2%` is stale
(head moved since). Temporary source-fix workflows are already removed;
only `tests/test_pr971_review_quality_regressions.py` remains. ADR 0032
stays Proposed while PR #971 remains open.

New gaps recorded, not resolved: issue `#1110` (measure
accepted-request to durable route-decision latency, `OPEN 2026-09-09`)
and issue `#1114` (export bounded authorized request-outcome
associations, `OPEN 2026-09-09`) are absent from this baseline.

Promotion contract still Draft: exact-head hosted `GREEN` is required
(`Hypothesis`, `Atheris`, `CodeQL`, supply chain, `dependency-review`,
`OSV`, `Trivy`, `Scorecard`, `coverage-evidence`, `opencode-review`,
`strix`, `scan-pr-queue`) plus a qualifying review. The `strix`
cancelled and `CodeQL`-compat failure are central-lane, not local.

## 2026-09-07 PR #971: fail-closed ambiguous bootstrap admission

External review thread `PRRT_kwDOTB3CTs6eh3BQ` identified that both
bootstrap selectors used provider/model-group passes and then let lexical
provider/model identity decide a capacity cutoff when price evidence was equal
or incomplete. Exact test-only commit
`eeb9cc1bafe579032ab48778fa08c24e0b3f0aa1` made those two cases executable;
Security and Quality run `34071330949`, job `101589111271`, failed exactly
`2 failed, 3490 passed, 2 skipped` because neither selector raised.

The smallest GREEN retains the existing provider/model-group availability
constraints but removes lexical identity as admission evidence: if a selected
and excluded candidate share the same comparable-cost state, including the
all-unknown state, selection fails closed with an operator action to provide
comparable price evidence or raise the limit to include the entire tied class.
No weight, quota, fuzzy identity, provider preference, or learned-quality claim
is added. The direct provider bootstrap selector promises exact model-group
spread; the discovery CLI selector additionally promises provider spread, so
consumers that need provider-level redundancy must use the latter boundary.
ADR 0032 is Proposed while this PR remains open. Status remains Proposed until
the successor exact head passes focused/full quality, security, and required
review lanes.


## 2026-09-07 PR #971: durable bootstrap selection order

Observation: exact predecessor `1e59d4fc9a628a898e404cd1bcacb412747c3b5b`
passed the unchanged full suite and coverage-guided fuzz lane, but external
review thread `PRRT_kwDOTB3CTs6elTYC` remained valid. The ephemeral bootstrap
report retained `select_model_group_diverse_models` order, while
`_synchronize_durable_agent_pool` converted the resolved identities to a set
and returned an alphabetically sorted tuple. A restart-backed report could
therefore discard the selector's cost/model-group order without changing pool
membership.

RED commit `98aed1a811cb894881b4c9aeb20de4f0b00fb634` adds a two-model
durable-pool contract whose selected order is deliberately the reverse of
agent-ID lexical order. The smallest GREEN retains a set only for membership
and collision checks, records resolved persisted identities in selector order,
activates them in that order, and returns the ordered tuple. It introduces no
new ranking, quota, provider heuristic, timeout, or dependency. Status remains
Proposed until the successor head completes the focused regression, full suite,
security, and required review lanes; the other three open #971 architecture
findings remain separate.

## 2026-09-14 trace-scope token (issue #117 acceptance item 9)

Issue #117's maintainer verification map, acceptance item 9, flagged that
`SecurityConfig.authorize` let a bare single `auth_token` satisfy the `trace`
scope unconditionally, with no test covering the raw library path (`server.py`
had `expected = self.auth_token` for scope `trace` whenever no
`bearer_verifier` was configured, regardless of split admin/inference mode).
ADR 0026 already documented the intended contract — inference or admin
authentication alone must not authorize a trace-bearing response, and split
static admin/inference mode should fail closed for trace absent a verified
claim — but `authorize()` did not implement that fail-closed branch.

Added an explicit `trace_token: str = ""` field to `SecurityConfig`. In
`authorize()`, scope `trace` without a `bearer_verifier` now resolves in three
modes: (1) a configured `trace_token` is the only credential that authorizes
`trace`; (2) with no `trace_token` and no split `admin_token`/`inference_token`
(single-token mode), `auth_token` keeps the documented local escape hatch; (3)
split admin/inference mode without a distinct `trace_token` fails closed with
the existing `401 unauthorized` — `admin_token`/`inference_token` never
satisfy `trace`. Wired `--trace-token`/`--trace-token-key` in `__main__.py`
exactly like `--inference-token` (KV credential name
`CONTEXTUAL_ORCHESTRATOR_TRACE_TOKEN` by default, resolved via
`get_credential`, no runtime env reads). The CLI's existing `--production`
gating (which requires split admin/inference credentials and rejects
identical admin/inference values) is unchanged: it only checks admin/inference
separation, not a trace credential, and every trace-bearing HTTP route already
gates on the caller's base admin/inference scope *and* the separate `trace`
scope over the same bearer, so split mode without a `trace_token` was already
structurally fail-closed for trace once `authorize()` was fixed — no new
startup requirement was added.

Raw-library-path tests in `tests/test_security_hardening.py`
(`test_single_token_mode_keeps_the_documented_trace_escape_hatch`,
`test_split_token_mode_without_trace_token_fails_closed_for_trace`,
`test_split_token_mode_trace_token_authorizes_only_trace`) cover all three
modes directly against `SecurityConfig.authorize`, including that
`trace_token` does not authorize `admin` or `inference`. One HTTP-level test
in `tests/test_chat_include_orchestration_trace_http_honesty.py`
(`test_split_token_mode_refuses_trace_with_inference_token_but_accepts_trace_token`)
shows a real `/v1/chat/completions` trace-bearing request is refused with the
plain inference token in split mode, and accepted once `trace_token` is
provisioned for that credential. Focused suite:
`tests/test_security_hardening.py`, `tests/test_chat_include_orchestration_trace_http_honesty.py`,
`tests/test_api_contract.py`, `tests/test_self_check.py`,
`tests/test_kv_credentials.py` (77 tests) pass; `interrogate` reports 100%
docstring coverage. Issue #117 acceptance item 6 (tenant/resource binding)
remains open.
## 2026-09-13 Output-budget clamp evidence (#1169)

`ModelClient._clamp_agent_token_budget` silently rewrote an explicit caller
budget (`max_tokens`/`max_completion_tokens`/`max_output_tokens`) down to the
served agent's published `max_output_tokens` ceiling with no error, header,
trace field, or usage marker telling the caller its budget was not the budget
applied — filed as #1169 during the local reproduction review of #1154
(removal of the global generation-token ceiling per #1151). ADR
[0130](planning/adrs/0130-output-budget-clamp-evidence.md) records the
decision to surface the clamp in-band rather than via a response header
(unavailable on the streaming path, since `_begin_sse()` flushes headers
before the provider call and its clamp decision exist) or a hard `400`
rejection (would break `noema`/`opencode`, which send a large `max_tokens` as
a ceiling, not a demand). `ModelClient` now records
`requested_output_tokens`/`effective_output_tokens`/`output_budget_clamped`
per thread (`_clamp_agent_token_budget_with_evidence` /
`take_output_budget()`, mirroring the existing `take_usage()` pattern), and
`TaskOrchestrator._invoke`'s non-race branch exposes it the same way it
already exposes assistant-message extras (`_last_output_budget`, mirroring
`_last_assistant_message`). The `route`/`conduct` trace-row builders attach
the three fields to the relevant provider-call trace row, and
`chat_completion_response` / `chat_completion_chunks` copy them onto the
existing `orchestration` extension object already used for `cost` and
`verification`. This now extends to the remaining call paths flagged as follow-up in the
initial cut: the multi-endpoint `immediate_race` branch (`TaskOrchestrator
._invoke`'s race `call()` closure also takes `take_output_budget()` and
records only the winning endpoint's evidence — a losing attempt's clamp
decision is discarded along with the rest of that attempt), structured/
`free_only` synthesis (`ModelClient._send_raw` now uses
`_clamp_agent_token_budget_with_evidence`, and `_orchestrated_provider
_completion`'s `send_synthesis`/final-response assembly carries the evidence
on the same ad hoc `orchestration` object it already attaches next to
`route`), and true-streaming passthrough (`ModelClient._stream_send` now
uses the evidence-recording clamp too, and `TaskOrchestrator.stream_route`
gained an `output_budget_callback` parameter — mirroring its existing
`usage_callback` — that `server.py`'s `_stream_route_completion` uses to
carry the evidence on the final SSE chunk's `orchestration` object, since
`_begin_sse()` has already flushed headers by the time the clamp decision
exists). Verified by `tests/test_output_budget_model_max.py` (clamped,
unclamped, and no-explicit-budget cases at the `ModelClient` and
`TaskOrchestrator` layers, plus one clamped/unclamped pair each for the race
winner, structured/`free_only` synthesis, and streaming-passthrough final
chunk) plus `tests/test_orchestrator_client_boundaries.py`,
`tests/test_true_streaming.py`, `tests/test_api_contract.py`, and
`tests/test_passthrough_provider_failover.py` (168 passed, 1 pre-existing
unrelated `openai` SDK version-pin failure), the full suite (3697 passed, 1
skipped, the same SDK version-pin failures plus one pre-existing unrelated
`mcp.Client`/camoufox environment failure), and `interrogate` at 100% on
`contextual_orchestrator/`. Not yet covered: the async-batch-submission call
site (`ModelClient._batch_run`'s `batch_body`/`_clamp_agent_token_budget`
call) has no synchronous trace or response to attach evidence to and remains
a separate follow-up.

## 2026-09-13 Free-pool selection ignored single-tool-call evidence (#940)

At `012beaac` the three mechanisms named in #940 stood at: capability
evidence implemented (`DiscoveredModel.supports_parallel_tool_calls`, probe
and 400 classifier from #1121, tags `tool_call:single|multi`), passthrough
400 failover implemented (`_is_single_tool_call_limit_error`), selection-time
exclusion missing: `_is_general_free_agent` checked only price and input
modality, so a `tool_call:single` agent was still chosen first for a
multi-tool request and one provider round-trip was wasted before failover.
Candidate on `fix/free-pool-single-tool-call-exclusion-940` adds a
request-shape predicate matching exactly the probe's rejected shape (two or
more tools without `parallel_tool_calls: false`, or an explicit `true`) and
passes the chat body at the two tool-carrying selection sites
(`proxy_completion`, structured `free_only` synthesis). RED: two new tests
failed with the single-call agent still served; GREEN after the change with
the single-tool, opt-out, and no-evidence shapes still served by that agent.
Not established: a live NIM confirmation that a one-tool request without the
flag is accepted (left to failover by design), and any change to
`general_free_serving_candidates`, which stays request-blind on purpose.

## 2026-09-12 Decision measurement startup gap

The supported server entrypoint did not expose the existing measurement option.
A default-off, explicit opt-in forwarding repair passes six focused contracts;
the broader warning-sensitive suite still has two parent-reproduced resource
failures. The [entrypoint record](doctoring/decision_receipt_integration.md#supported-entrypoint-repair-2026-09-12)
tracks 91 open PRs, 16 file overlaps and the actual hunk audit. Complete cohort
reconciliation, independent outcome adjudication, real KPI improvement, hosted
acceptance and deployment remain unverified.

## 2026-09-12 Title-only psychometric citation gap

Research parent `14a6a943` cited Fox and Glas (2001) without an identifier,
so passing identifier checks missed its absence from the paper inventory.
The verified DOI and APA entry now connect that lead to the existing guard.
The [reproduction record](doctoring/autonomous_kpi_runbook.md#title-only-citation-reconciliation-2026-09-12)
records RED and six passing citation contracts. This closes one known discovery
omission, not complete paper coverage. Full-method review, owner implementation,
observed accuracy/latency improvement and protected delivery remain unverified.

## 2026-09-12 Nonlinear response-process evidence gap

Follow-up classification repair: RED `c8b358ad` reproduced a dry-run report
being labelled for production-candidate review (1 failed, 1.87s). Runtime
`383b4a1e` marks assembled dry-run reports `synthetic_diagnostic_only` and
`benchmark_smoke_only`, preserving live sufficiency logic and the null routing
recommendation. Both benchmark test suites passed: 126 tests in 8.65s,
session 70083, exit 0. Independent read-only tracing found the misleading
classification in published JSON/Markdown but no inspected deployment consumer
that uses it to activate policy. This repairs evidence classification, not a
demonstrated promotion bypass or measured accuracy/latency gain. Full suite,
installed artifacts, rendered output and hosted review remain unverified for
this repair; earlier research-branch runtime acceptance does not cover it.

Evaluation readiness probe at `4359401f` ran the documented NIM command with
`--dry-run --pricing-scenario examples/nim_pricing_scenario.json` and isolated
output `/tmp/co-kpi-readiness-20260912.r1sYeS` (session 75417, exit 0).
It completed 589 simulated requests, with 30 paired tasks and no production
recommendation. All policy scores were zero and reported latency was the
fixed 1 ms test value: neither is an observed KPI baseline. The generated
report labels `decision_use=production_candidate_review` despite dry-run mode;
admission semantics require audit before this label can support any decision.
The readiness command proves harness execution only. No provider egress,
observed cohort, independent adjudication, initial-decision p95, or production
promotion was verified by this probe.

Research baseline `60ee94c2e941d2883aca623867138798e2ba9bc9`, PR #1107:
[external psychometrics intake](doctoring/lart_measurement_review.md#nonlinear-dependence-external-psychometrics-intake)
adds a diagnostic alternative to monotonic token-length assumptions. Proposed
owner work belongs in fast-mlsirm; CO consumes a released calibration contract.
Keep post-response observations out of the same request's initial routing
features, and separate decision latency from generation and queueing time.
No estimator, production default, observed KPI, or protected-main delivery is
established by this literature addition. Remaining work includes full method
audit, lawful observed data, held-out diagnostic comparison and frozen-policy
accuracy/decision-latency measurement. Rendering of this addition is unverified.

## 2026-09-09 Optimizer score-domain repair finding

Independent exact-source probing at
`204e306c046797b812589b9b66062296beaa1c8d` found that the shared
`_score_config` boundary accepts nonfinite and out-of-range callback scores
despite its public `[0,1]` contract. In both serial and batch mock paths,
NaN, infinity, and 1.1 could recommend an invalid candidate over a valid 0.9
candidate. The 0.44-second probe used AST-extracted functions, not installed
package or real-provider execution. Subsequent public optimize/evolve RED
at `98153df6` produced 20 failed invalid-score cases and 20 passed compatibility
cases. Shared repair `db700768` rejects each invalid score before aggregation.
Frozen review checkpoint `22246762e3ce0b7e8624d457d8905835565d6a5a`
passed 86 focused tests in 3.04 seconds, including invalid observations whose
mean is valid. Preserve valid
fractional scores; reject invalid evidence rather than clamping or omitting it.
This protects recommendation integrity, not a measured customer accuracy gain.

Isolated wheel execution `22123` passed 48 public score-domain tests in
0.93 seconds outside the checkout, using Python `-I`. Root independently
confirmed the installed import and wheel SHA-256
`8dea451f3722dc91b3f4e9c10bfc9b55ab3372e39a2f49aeb5a027d67fce28f3`.
The installed environment resolves declared dependencies; the separate live
full suite `78368` uses the frozen project lock. Those environments are not
claimed identical. Full-suite, hosted acceptance, protected merge, and release
remain pending. The guard does not claim early provider-call cancellation or
recovery of spend already incurred before score validation.

The separate provider-truncation hypothesis was rejected: `batch_route` returns
the ordered input cardinality or raises, and existing missing/content tests
preserve incurred spend. Merged PR #961 owns that earlier provider repair;
a short-list test double alone would not establish an actual provider defect.

## 2026-09-09 Batch recovery PR delivery

[PR #1115](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1115)
is Ready/Open at `73404f89d7a90f7a6b98caf514af859b02a375dd`, based on
#1113 `af8d732e6cfc9c0169ac850f875f42f1db7eecd4`, delivered without force.
Full-suite execution `82637` completed with **3,491 passed, 2 skipped in
757.78 seconds**, supplementing the separate **69 installed-package tests**.
Root verified the live head/base and empty review inventory. Hosted Security
run **34333545448** completed all three jobs successfully on tested merge
`138fa7aca0554d5695137a1cfa6b74a48b26715d`. Linux/Python 3.12.14 hosted
full suite: **3,491 passed, 2 skipped in 785.64 seconds**; benchmark/docstring
checks: **134 passed in 10.85 seconds**; installed wheel checks: **40 passed
in 15.85 seconds**. Hosted core wheel SHA-256:
`4c34fdc911270ab07297fdd7bbf782e8ee4368547e879f288cf9c3805ed3798e`.
Current PR head/base still match the above revisions, Ready/Open with no reviews.
No independent approval,
protected merge, release, remote-provider integration, or observed KPI gain is
established. The untracked local native extension was not committed.

## 2026-09-12 Retained export validation repair (Proposed)

PR #1138's repair `7ebf577535139c6655a1b8d360682511defc22ba`, based on
`d1a080d7bd9de4e37aa72a7f98f9414abc0362fc`,
preserves fixed-cutoff initial/final decision provenance across 257 admissions
and rejects disabled measurements instead of presenting an apparently empty
cohort. Malformed phases remain counted and missing durations remain null.
Focused actual-native validation passes 62 tests with warnings-as-errors; after
test-only root lifecycle repairs the six-module expansion passes 124 tests with
process exit 0. All 23 isolated failure-union nodes now pass; a fresh noneditable
core/native wheel installation outside the checkout passes the same 124 tests.
No customer accuracy or
decision-latency gain, hosted acceptance, release, or deployment is established.
See [the validation runbook](doctoring/request_outcome_export_validation.md)
for RED/GREEN evidence, parent comparison, reproduction, and remaining gates.

## 2026-09-09 Request-outcome export gap

[Issue #1114](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1114)
records an installed-wheel HTTP probe at frozen `73404f89`: batch submission
returned 201 with durable lineage and one committed association, while the
200 analytics snapshot omitted the submitted batch job ID. Execution `83174`
completed successfully as an observation probe, not a passing assertion that
the proposed export exists. Its script is
`/tmp/co-batch-export-probe.s0ytig/probe_export.py` on the validation host.
The correct `measurement_complete=false` remains unchanged.

Independent source review confirms associations currently support internal
recovery, not an operator outcome-link export. The next delta is a bounded,
prompt-free, purpose-authorized join preserving many-to-one links, cache
provenance and unmatched/failed admissions. Existing admissions are not
owner-filtered; do not expose a global join through owner-scoped replay or
infer ownership from request IDs. Recovery descriptors and private payloads
must stay excluded. This operational capability is needed before collecting
the requested observed KPI cohort; it does not supply adjudicated outcomes.

Successor `codex/request-outcome-export-20260909`, based on `73404f89`,
established actual HTTP RED at `3e14dfbbb87e8cc22a98ddd9e6ebb8ed576c0021`:
**1 failed in 5.37 seconds**, terminal execution `24161`. After successful
workflow/batch requests, an invalid admission, and SQLite restart, the proposed
admin export returned 404; an inference principal was denied with 401.
This is not installed-successor evidence. Design review found keyed workflow
replacement deletes prior versions, so a high-water query alone cannot promise
historical reproducibility. The successor must retain the necessary prompt-free
association revisions in the same journal transaction or otherwise prove the
claimed snapshot semantics; missing legacy history cannot be fabricated.

Successor checkpoint `f0304d7bab409823ab17f8b0d3f08f69701441d0` now has
**68 focused tests passed in 23.08 seconds** (execution `55267`) and a clean
bounded independent source review of persistence/privacy. Root review found a
separate HTTP parsing gap: default query parsing discards empty values before
unknown/duplicate validation. Blank-query RED/fix is pending after the live
frozen full-suite execution `50159`; no source or environment mutation during
that execution is authorized by this receipt. Proposed ADR 0131 and the
runbook record the service-wide admin boundary; no independent purpose-claim
verification is supplied by the existing external verifier.

Direct browser inspection of the temporary local runbook first viewport
(`1265×712`, English) found its heading and PRD text legible. The ADR preview
(`1129×1022`, English) exposed a renderer defect: YAML frontmatter became
merged prose/list content. This is being repaired in the temporary renderer,
not hidden by changing the source ADR. Whole-document and rendered UML
acceptance remain pending. Neither inspection establishes deployed UI quality.

## 2026-09-09 Installed batch recovery validation

Frozen `73404f89d7a90f7a6b98caf514af859b02a375dd` produced separately built
core and native wheels. Isolated installed-package execution `31999` completed
**69 batch-lineage and decision-receipt tests in 44.46 seconds**, exit 0,
on macOS arm64/Python 3.14.6. Root independently verified outside-checkout
imports resolve under `/private/tmp/co-batch-installed-73404f89.cX4GMN/venv`
for both the core package and native extension. No editable source import is
used in this receipt. Core SHA-256:
`d51ea2844064a5f5674791c6ef7789a0a277d1eae43fe49d506f4ccaa120a18c`;
native SHA-256:
`fb0a88ff477f422d496720d551f051a06172c848d2a6bc95d7caaa5e95bc87ea`.

At this installed-package checkpoint the separate full-suite execution `82637`
was live; it subsequently passed as recorded in the delivery section above.
Installed focused success alone does
not prove full-suite or hosted success, real remote integration, review
approval, protected merge, publishing, or customer KPI improvement.

## 2026-09-09 Hosted outcome-link acceptance receipt

PR #1113 head `af8d732e6cfc9c0169ac850f875f42f1db7eecd4`, based on
`c7345670e08f029ad3aa5dd1133037bb4b451d9b`, completed repository Security
run **34329594602** successfully. Its tested merge was
`e127f7a0aef94949a4a8f3eb16371e155f370fb1`, not a protected-main merge.
Linux CPython **3.12.14** tests/package job **102394807283** reports
**3,462 passed, 2 skipped in 756.10 seconds**, benchmark/public-docstring
checks **134 passed in 10.00 seconds**, and installed-wheel checks
**40 passed in 15.72 seconds**. The built core wheel SHA-256 is
`e705cec46453123eae92b0c7979b6bde13a479afb5e021978c2defe849e995d8`.
CodeQL/supply-chain/SBOM job **102394807100** and fuzz job **102394807264**
also completed successfully. Evidence: [terminal run and job logs](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34329594602).

The current-head review inventory remains empty. These hosted results supplement
the separately recorded local installed-wheel request/outcome tests; they do not
replace independent approval, protected merge, publisher acceptance, or measured
customer accuracy/latency. The unpushed batch recovery successor is a different
revision and does not inherit this test result.

## 2026-09-09 Batch restart recovery checkpoint

The isolated batch successor, based on #1113, retains the failed restart
experiment `d71bcc0a`: **1 failed in 1.96 seconds**. Remote submission succeeded,
but after registry failure and restart the authenticated owner received 404;
another owner correctly received 404 without a remote download. Runtime
`853e860946d2d55a06d824e042057806c3ad79d8` then passed **73 focused tests in
21.17 seconds** (terminal execution `86930`). Documentation checkpoint
`b4abdd660b0ee44fd1a5b7a8b8c7a7ad5d1e1f92` remains unpushed.

The candidate reuses an indexed durable submission event for an owner-bound,
expiring, prompt-free recovery descriptor. Focused cases cover target mismatch,
malformed descriptors, unexpected result IDs, missing usage, and no resubmission.
This is not acceptance: independent review and additional RED cases must check
registry reads/writes that remain unavailable during recovery, and consistency
between submission-envelope item IDs and restored descriptor IDs. Full-suite,
installed-package, hosted, protected-merge, and release evidence remain absent
for this candidate. Simultaneous durable-store and registry failure cannot be
reported as recoverable. No observed customer KPI improvement is established.

Follow-up checkpoint `e372bc542f8fbec8d047a9affae15c018698d48a`
reproduced **3 failures in 3.59 seconds**: continuing registry outage, inconsistent
submission/item identities, and inconsistent estimate keys. At
`7fb1a71ce1b4c14d1ba29e12501ba22fb589cca9`, **19 tests passed in 14.94 seconds**
(terminal execution `37121`). Recovery metadata now travels with the authorized
request instead of requiring another registry write. Independent source review
found no additional silent usage/model-attribution defect in this diff: absent
prompt estimates do not fall through to estimating an empty reconstructed prompt.
That review does not cover all existing attribution behavior. Remaining checks
include coordinator-registry hits with missing backend metadata, malformed job
field types, and a changed deployment using the same backend alias. A backend
alias or API path alone cannot establish service/account identity.

At `aaa9b133`, the focused suite reports **82 passed in 31.21 seconds**
(terminal execution `6240`), and independent source review clears the preceding
typed-identity and partial-registry findings within its inspected scope. Root
end-to-end review nevertheless identified two remaining paths before full-suite
acceptance: the Pg adapter writes its own registry after remote acceptance but
before returning the handle to the coordinator, and healthy registry reads
refresh retention whereas recovery descriptors use a fixed expiry. Reproduce
backend-registry submission failure without losing the accepted handle; also
ensure an expired recovery descriptor does not invalidate otherwise healthy,
authorized, complete registry state. Expired recovery with missing registry
state must remain denied. These findings supersede any bounded recommendation
to freeze the candidate for full-suite verification.

Those paths were reproduced independently: backend submission checkpoint
`17cfa611` failed once in **0.95 seconds**, and its `8ddfeb9f` repair passed
the focused case in **1.79 seconds**. Healthy-expired checkpoint `df638d6c`
failed once in **1.51 seconds**; `a6b94855` then passed **84 tests in 32.63
seconds**. Review found its healthy fast path skipped the new deployment
binding. Checkpoint `08a660dc` reproduced that regression (**1 failed in 1.41
seconds**); `cd38d9c4811deb6e9fde9c0c11a78869d9f39dcf` passed **85 tests in
34.48 seconds** after persisting and checking the binding. Full-suite acceptance
is still deferred: healthy metadata must also preserve the endpoint comparison
already required by descriptor recovery. This is a demonstrated contract
inconsistency, not demonstrated cross-service data disclosure. Legacy unbound
jobs must have an explicit compatibility test; they cannot count as validated
deployment-bound recovery.

Endpoint checkpoint `c06615ab` reproduced the healthy-path mismatch (**1 failed
in 2.09 seconds**). Runtime `450667593285679c92d1d0a698f35eadb2b2c879`
passed **86 focused tests in 36.58 seconds** (terminal execution `63908`).
Independent read-only review confirms endpoint equality now applies to new
bound metadata; missing endpoints remain compatible only for explicitly unbound
legacy records. Documentation head `73404f89d7a90f7a6b98caf514af859b02a375dd`
is frozen for full-suite and separate installed-package verification. Neither
has a completed result yet; this checkpoint is not hosted or released evidence.

Visual receipt: the GitHub-rendered document at
`aee00ac9da1e7f17ddfaec4ad3ebbafc06dee01f` was opened in the actual browser,
and its screenshot directly inspected at **1265 × 712**, English. The title,
recovery heading, first paragraph, and full revision strings were readable
without overlap or horizontal clipping in that viewport. The screenshot is
inline in the validation task. Lower sections and other viewports/locales were
not inspected; this does not constitute product UI acceptance.
## 2026-09-09 State persistence integrity prerequisite

PR [#1108](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1108)
repairs a reproduced failed-replacement data-loss case in the common SQLite
state writer. Code `d7bba88f3d711883a37effe49ab4f503c4fb8e01` rolls back failed
writes under the existing lock. Test follow-up `f1abe1e3` checks that no
transaction remains immediately after failure and that both the previous and
unrelated subsequent records survive reopening the database. The persistence
suite passed 19 tests in 9.28s; this is not a latency or customer-accuracy result.

Full local suite at `877d5112ed470d851afaa2c746b94393cc768ee7`: 3,396 passed,
2 skipped, exit 0 (883.03s). Test-only follow-up
`716e012dcb50857000b0fc53c89c6434fdf7e7c2` covers a deferred commit failure
with real SQLite constraints; persistence, workflow authorization, and governance
tests pass together (29 passed, 4.89s). Full-suite evidence remains attached to
the earlier head, not silently reassigned to the new regression.

At the earlier PR head `aa674187b0341c7852f85c27fb696aec21f1a799`, GitHub
reported zero check runs and two success statuses whose descriptions explicitly
said reviews were skipped (Draft; expired trial/no credits). Those statuses do
not establish review approval or security validation. Keep protected merge and
release pending actual exact-head evidence. The root cause and reproduction are
in the [canonical runbook](doctoring/autonomous_kpi_runbook.md).

## 2026-09-09 Stacked quality-trigger repair

Correction: PR #1066 at `59a8f4eadfe0e0dcc5ff47cf1acfb80403e241ad` already
owns this repair and its Ready/closed admission checks. The partial local repair
described below missed that lineage. Its full branch was integrated at `d721e04b`
without force, with the extra filter/permission assertions consolidated into
the owner's `tests/test_repository_security_metadata.py`. The duplicate test
file is removed after preserving those assertions. #1066 and #1060 stay open;
integration is not protected delivery. The #1108 hosted run
`34316962950` at `c11df645` completed with **1 failed, 3,399 passed, 2 skipped
in 737.97 seconds**. The single failure was the existing metadata assertion
for the old concurrency key, omitted by the partial repair. Fuzz and
CodeQL/supply-chain/SBOM jobs passed. This was a contract-update omission,
not a flaky test. Full #1066 inheritance repairs that assertion.

The non-force integrated #1108 head `129a665016ed1acd79ae12915c905b1020856fcc`
passed **42 metadata, NIM workflow, and persistence tests in 4.19 seconds**;
actionlint and diff-check also passed. New hosted run `34318012080` was que…96633 tokens truncated…`describe_message_count` cannot account for, so wiring it in would only ever
compute `None` there; the batch-upload send path (`_batch_run`) is a separate
async transport (job upload/poll, not a live per-request send) and stays on
the plain catalog clamp; embeddings (`_send_raw` called from
`embed_with_usage`) never carry chat messages and are untouched. The
passthrough response body itself is deliberately left with no
`shared_context_budget` field: this transport's own module contract is that
"the full provider response shape... survives verbatim" for tool-loop
callers, so adding an extra top-level key there would violate that contract;
only the outbound request-shaping decision (send/clamp/reject) applies to
passthrough, not response evidence. Local evidence only: the new and touched
tests pass (`tests/test_true_streaming.py`, `tests/test_output_budget_model_max.py`,
`tests/test_token_counting_boundaries.py`,
`tests/test_prompt_count_source_http_honesty.py`, `tests/test_api_contract.py`,
`tests/test_self_check.py`), `python -m interrogate -v contextual_orchestrator/`
reports 100%, and the full `tests/` run (3723 passed, 2 skipped) is green
apart from the same five pre-existing, unrelated local-only `openai` SDK
2.54.0-pin and `mcp.Client` failures tracked elsewhere in this document.

### Streaming terminal-frame shared-context evidence ordering hazard — fixed

Review of the streaming follow-up above found an ordering hazard it did not
account for: `TaskOrchestrator.stream_route`'s post-stream real-time judge
(`policy.realtime_judge`, on by default; see its "Real-time judging after the
stream" comment) issues its own provider call on the same thread — through
`_model_judge_verification` -> `_FastMLSIJudgeAdapter.complete()` ->
`ModelClient.chat()` — and `chat()` unconditionally clears, and can
repopulate with *its own* evidence, the thread-local shared-context-budget
accessor at entry. `server._stream_route_completion` read that accessor via
`server._take_shared_context_budget()` only after `stream_route` had already
returned, i.e. after the judge's own call had run and potentially overwritten
it — so the terminal SSE frame could carry the judge's `shared_context_budget`
evidence, or none at all, instead of the served request's. This is the same
dishonest-evidence failure mode this document's honest-metrics principle
forbids, just on the streaming success path rather than the accounting
surfaces this document otherwise tracks.

Fixed by capturing the served request's evidence *inside* `stream_route`,
immediately next to the pre-existing `take_usage()` call and before the judge
runs, following the exact pattern already proven for usage: a new optional
`shared_context_budget_callback` parameter (mirroring `usage_callback`'s
shape) hands the caller the evidence at that point. `server
._stream_route_completion` now passes this callback — guarded by an
`inspect.signature`-based duck-typing check so a minimal test double whose
`stream_route` does not accept the parameter still works, falling back to the
old post-hoc `_take_shared_context_budget()` read only in that case — and
uses the captured value for the terminal frame. The non-streaming response
path's `_take_shared_context_budget()` call is unchanged: it already reads
before any judge call runs and was never affected by this hazard.

`prompt_count_source` was audited for the identical hazard and confirmed
safe, not just assumed so: `server._prompt_count_source(orchestrator,
messages, model_name)` derives its answer purely from the request's own
`messages`/`model_name` via the counting-provenance registry, never from any
`ModelClient` thread-local state, and — unlike `shared_context_budget` — it
is not even emitted on the streaming path today, so there is nothing on that
path for a second call to clobber.

New regression coverage:
`tests/test_true_streaming.py::test_http_route_stream_terminal_frame_survives_realtime_judge_second_call`
installs a working (not neutralized) fast-mlsirm judge whose `.judge()` makes
a real second provider call through the adapter, and asserts the terminal
frame still carries the served request's `shared_context_budget`
(`prompt_tokens`/`output_ceiling`), not the judge's. Verified to fail against
the pre-fix code — the terminal frame carried the judge's own
`prompt_tokens`/`output_ceiling` instead of the served request's — before the
fix landed. Local evidence: `tests/test_true_streaming.py`,
`tests/test_output_budget_model_max.py`,
`tests/test_prompt_count_source_http_honesty.py`,
`tests/test_token_counting_boundaries.py`, `tests/test_api_contract.py`, and
`tests/test_self_check.py` all pass, and `python -m interrogate -v
contextual_orchestrator/` reports 100%.


## 2026-09-09 Autoresearch loop: autonomous KPI scope, PR #1108 verification, hourly-prompt hardening

PRD/Goal adjustment: KPI scope was selected autonomously under
`docs/analytics_spec.md` without asking (see the runbook scope entry).
Loop metric `open_pr_count` is 87 on recount (baseline 85; growth from
concurrent sessions). PR 0 only via merge or verified-successor
full-delta inheritance; single-writer deltas are integrated, never
discarded; no force-push; close only on user instruction, no valid
delta, malicious change, or verified complete inheritance.

- **PR #1108 (fix(persistence): roll back failed state replacements):**
  valid minimal root-cause fix. `_save_sync` now runs under the writer
  lock plus the SQLite connection context so a failed keyed replacement
  rolls back instead of leaking its DELETE into a later unrelated commit.
  Isolated-worktree evidence at head `4316be85`:
  `tests/test_persistence.py` 20 passed in 32.42s, exit 0 (insert-phase
  and deferred-commit-phase failures, closed-transaction checks,
  reopen persistence). Unit evidence only. The PR is `dirty` against
  loop HEAD `0ea2a58d` because both sides appended to this baseline
  file; code auto-merges. Action: owner restacks with a normal merge
  and manual docs resolution; this loop does not push to that branch.
- **Current HEAD `0ea2a58d` (`benchmark_priors.py` calibration bound):**
  docstrings/comments only in effect; `tests/test_model_group.py` plus
  `tests/test_benchmark_priors.py` 37 passed in 25.82s, exit 0. No
  runtime, routing-default, or numerical-formula change; no customer KPI
  claim.
- **Actions concurrency (reviewed, no change):** `security.yml` groups by
  `local-quality`-repository-event-PR/schedule/ref with same-group
  cancel only, so distinct PRs stay independent and pushes/schedules
  serialize on ref/schedule; the hourly loop uses its own
  `opencode-hourly-loop` group with `cancel-in-progress: false` and never
  cancels merge/release/deploy/migration. Renaming groups without an ADR
  would churn CI for no functional gain; left as is.
- **Hourly prompt:** `.github/opencode/  hourly-loop-prompt.md` now records
  the shared-checkout, live-handle, synthetic-vs-observed, and PR-0
  rules so the next scheduled pass inherits them without re-derivation.
  Follow-up: keep #1079 (main-protection stale job names) with the
  owner; keep #1075 closure with the owner; re-observe #1108 after its
  restack and hosted checks.

## 2026-09-09 Autoresearch loop: PR #1109 atomicity review, no merge, prompt stacking rule

KPI reaffirmation (no scope question asked): `open_pr_count` 88
(baseline 85). #1109 is a new draft on the psychometric stack
(`codex/psychometric-kpi-successor` base); #1108 is still `dirty`
against the loop branch; #1094 is still protection-blocked. No PR met
the merge bar this turn (terminal-success checks plus resolved threads
plus independent exact-head approvals), so no merge, readiness flip, or
cross-session push was attempted.

- **PR #1109 (fix(psychometrics): preserve evidence when observations
  are rejected):** read-only review plus isolated verification. The
  reorder validates before mutating retained vectors, order, and
  revision under the existing lock; valid-input behavior is preserved
  and no new Python-side numerical arithmetic is added. Isolated
  evidence at head `4cc0bf2c`:
  `tests/test_psychometric_observation_atomicity.py` 6 passed in
  52.15s, exit 0. Hosted checks: CodeQL success; tests and fuzzing still
  in progress at observation time. Unit evidence only; full regression,
  independent review, protected merge, and release remain pending.
  Action: leave the draft with its owner stack; re-observe after hosted
  checks complete.
- **Hourly prompt (this hour):** added the single-writer stacking rule
  (integrate deltas, normal-merge restack only, never flip another
  session's Draft) and the PRD/TRD case-preservation rule alongside the
  existing fail-closed ordering guidance.

## 2026-09-09 Autoresearch loop: PR #1109 Ready flip and integer-index hardening, still unmerged

KPI reaffirmation (no scope question asked): `open_pr_count` 88
(baseline 85). #1109 is now Ready (`draft: false`, `mergeable: true`,
`mergeable_state: unstable`); #1108 is confirmed `dirty` again; #1094
remains protection-blocked. No PR met the merge bar (terminal-success
checks plus resolved threads plus independent exact-head approvals), so
no merge, readiness change, or cross-session push was attempted.

- **PR #1109 new head `b8d2651d`:** the owner hardened validation from
  `int(value)` to `operator.index(value)`, rejecting fractional rows,
  whole-valued floats, and numeric strings that truncation previously
  masked as valid dichotomous data, while keeping the integer protocol
  including `numpy.int64`. Isolated evidence: 19 passed in 13.68s, exit
  0. Hosted checks: both CodeQL jobs success; tests and fuzzing still in
  progress; no reviews yet. Unit evidence only; full regression,
  independent review, protected merge into the owner stack, and release
  remain pending. Action: re-observe after hosted checks and first
  review; do not merge across the stack boundary from this loop.
- **Hourly prompt (this hour):** queue-exhausted continuation now
  explicitly names gap development plus ContextualWisdomLab repository
  and connector linkage under responsibility boundaries, so scheduled
  passes do not idle after the PR list drains.

## 2026-09-09 Autoresearch loop: PR #1109 fuzzing green, tests pending, failure-never-idles rule

KPI reaffirmation (no scope question asked): `open_pr_count` 88
(baseline 85). #1109 head unchanged (`b8d2651d`): fuzzing success is
new since last turn, tests still in progress, no reviews, still
`unstable` — the prior 19-pass isolated verification stands and no
merge was attempted. #1108 mergeability is `unknown` (recomputing);
#1094 remains protection-blocked.

- **Hourly prompt (this hour):** a failing check never idles the loop —
  fix and rerun owned failures immediately while continuing safe
  independent work, and codify manual workarounds with log-grounded RCA
  for PYTHONPATH, Actions, and execution errors.

## 2026-09-09 Autoresearch loop: stacked-quality merge adopted, #1108 restack verified, #1105 pending-verdict diagnosed

KPI reaffirmation (no scope question asked): `open_pr_count` 88
(baseline 85). No PR met the merge bar, so no merge, readiness change,
or cross-session push was attempted.

- **Loop merge `d721e04b` (adopted, reviewed):** the stacked-quality
  repair now on this branch is compliant — exact
  `{workflow}-{repository}-{PR}` concurrency with same-group PR-only
  cancellation, expanded stacked-PR coverage, Draft/closed-only skips,
  and test consolidation without dropped assertions (see runbook for
  the clause-level verdict). Action: none; keep.
- **PR #1108 restacked head `c11df645`:** isolated evidence 21 passed
  in 28.10s, exit 0 (prior 20-pass run superseded). Mergeability still
  recomputing. Action: re-observe; owner restacks with normal merges.
- **PR #1109 head `b8d2651d`:** all hosted checks green, still no
  reviews — awaiting independent approval on the owner stack. Action:
  re-observe.
- **PR #1105 (Ready, `main` base):** 3 CodeQL-compat failures are
  pending-verdict fail-closed (`DISPATCH_OUTCOME: success`,
  `VERDICT_STATE: pending`, self-rerun promised), not code defects.
  Action: re-observe next turn for self-heal; owner owns any real fix.
- **Hourly prompt (this hour):** never make a full foundation or mutual
  official release a precondition — cut owner/consumer cycles with a
  minimal contract, port, or ACL and complete independently verifiable
  functionality first.

## 2026-09-09 Autoresearch loop: #1108 loop-merge absorbed, #1105 still unhealed

KPI reaffirmation (no scope question asked): `open_pr_count` 88
(baseline 85). No PR met the merge bar, so no merge, readiness change,
or cross-session push was attempted.

- **PR #1108 head `129a6650`:** owner merged the loop branch with a
  normal merge (no force). The fix files are byte-identical to the
  verified head, so the 21-pass evidence stands. Mergeability
  recomputing. Action: re-observe for clean state, then hosted checks.
- **PR #1109 head `b8d2651d`:** still clean, still no reviews. Action:
  await independent approval; re-observe.
- **PR #1105 head `b655fe1b`:** same 3 pending-verdict failures, no
  self-healing rerun observed yet. Action: re-observe; owner owns any
  real fix.
- **Hourly prompt (this hour):** wrong closes are recovered through
  reopen or successor and never left closed (close only on the four
  evidenced conditions).

## 2026-09-09 Autoresearch loop: all PRs static, fetch transient absorbed

KPI reaffirmation (no scope question asked): `open_pr_count` 88
(baseline 85). No PR met the merge bar, so no merge, readiness change,
or cross-session push was attempted.

- **PR #1109 / #1108 / #1105:** all heads unchanged; prior isolated
  verifications stand (19-pass and 21-pass). #1109 clean without
  reviews; #1108 mergeability recomputing without reviews; #1105 still
  blocked on the same 3 pending-verdict failures. Action: re-observe
  all three next turn.
- **Sync incident:** one fetch refused the remote-tracking ref update;
  retry plus ancestry check plus fast-forward-only resolved it with no
  rewrite. Lesson recorded in the runbook: never infer a rewrite from a
  refused ref update.
- **Hourly prompt (this hour):** record merge and delete rationale
  before committing; remove self-modifying or source-fix workflows
  whose purpose is done.

### PR #1108 terminal repair evidence, 2026-09-09

At head `129a665016ed1acd79ae12915c905b1020856fcc`, base
`2996cd3c360444b792d499f3b09a783abdd830c2`, hosted run
[34318012080](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34318012080)
completed successfully. Checkout log records merge `9516d1d` of those revisions;
tests job `102358241912` reports **3400 passed, 2 skipped, 734.73 seconds**, plus
134 package/docstring checks passed in 10.61 seconds. All four actual check runs
were successful. This supersedes the earlier metadata-assertion failure for
current-head CI only; it does not erase that failure or establish a protected
release. The Ready PR still has no reviews. Next gate: independent review and
protected stack integration, preserving the canonical #1066 workflow delta.

Research source `7734e89c` adds the bounded Bolsinova–Tijmstra response-time
follow-up and prohibits outcome leakage in the proposed joint-model comparison.
The DOI discovery check caught its missing inventory entry (one failing test);
after linking the source, all six paper contracts passed in 6.23 seconds.
No observed-task accuracy or decision-latency improvement has been measured.

### Decision-measurement pre-release review, 2026-09-09

Candidate `01ce9035715fab4ed60e7352caa85512f855e0bb` for
[issue #1110](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1110#issuecomment-5597096146)
is not release-ready. Read-only call-site review found that server `_run`
is called inside embedding retry loops and file-replica deletion. Admission
inside that helper counts attempts as requests and starts some clocks after
selection. Repair: one validated request-owned admission, explicit endpoint and
measurement unit, separate attempts, and a first-failure/second-success regression
that retains exactly one admission. File operations and evaluation batches must
not silently become individual generation samples.

The automatic proxy also acknowledged selection before file binding and effort
configuration could reject the request. Move acknowledgement after those checks,
immediately before transport, and prove rejection produces neither dispatch nor
a committed decision. The existing persistence store does not bound the three
new receipt kinds; all-record export is unbounded in memory. Cohort-aware export
and explicit retention remain required. A successful isolated package test does
not resolve these semantic findings. The assigned implementation agent is repairing
them; no routing default or release was changed.

Integration checkpoint `07957ee643bf74c5beb13c03827f59331307cc5d` normally
merges #1108 head `129a6650` into the measurement branch. The implementation
agent reports terminal receipt/persistence verification: **34 passed in 5.88
seconds**; this is focused local evidence, not full CI or package acceptance.
The checkpoint still needs per-invocation race identity, indexed phase lookup,
trusted HTTP identity integration, and remaining endpoint coverage.

A root-run in-memory SQLite plan comparison used the checkpoint's table and
index definitions: the JSON-filtered phase query searches only by `kind`;
the proposed `(kind, key, seq)` index with `key IN (...)` searches by both
`kind` and `key`. Both plans use a temporary ordering B-tree. This validates
the proposed lookup shape only, not a measured customer latency improvement.
Keep historical records, validate migration identity, and test rollback before
adopting the index/backfill. The implementation agent owns that change.

At committed candidate `05b512effe0045340224e5e0408ae984f5784d1e`, an
independent read-only review found that a successful answer-cache return bypasses
selection hooks and can finalize as `unfinished`. The required HTTP regression
uses two identical authenticated requests: two admissions, one provider dispatch,
and a distinct cache-hit terminal outcome with absent provider-selection duration.
Keep the cache hit in the accepted denominator. This is tracked in
[the existing owner issue](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1110#issuecomment-5597507862),
not a separate implementation branch.

The in-progress auxiliary/task repair has a reported cold/warm triage HTTP result
of one passed test in 8.72 seconds, but it ran on an uncommitted delta over that
candidate. It is development feedback, not exact-head acceptance. Root inspection
also found that the new auxiliary records were not yet included in the bounded
receipt export. Export the same admission cohort's component evidence and test
it before claiming component reporting. A provider-ready timestamp preceding a
diagnostic write is not evidence of the actual network-send instant. Generated
planning, evidence embedding, and answer-cache outcomes remain explicit coverage
items; no customer KPI gain or release is established by this checkpoint.

### Native packaging and release owner, 2026-09-09

Root independently inspected the native wheel built from candidate `9707a5e1`:
SHA-256 `e0bf63d790256c6d4eba8598c131d63188a994c899df5124bd9eadf2cc39c568`.
Its five entries contain only the extension and distribution metadata/SBOM, not
core Python sources. The hypothesized source-file collision was not observed;
retain the existing namespace and verify both manifests rather than rename
without evidence. Clean-checkout CI still needs native build/install and
outside-checkout core/native acceptance. Local ABI success is not Linux or
hosted-CI proof.

The existing canonical release owner is
[organization issue #1552](https://github.com/ContextualWisdomLab/.github/issues/1552),
verified open. At organization main `7fd571dbcdbae6acf29d8f4ee704d7ba6297e4db`,
the inspected `exact-artifact-sbom-attestation.yml` reusable component attests
artifacts; it does not publish packages. CO owns its build adapter and package
acceptance; generic release eligibility, immutable tagging, and idempotent
delivery remain with that owner. The verified organization publishing secret
names are `PIPY_TOKEN` and `CARGO_REGISTRY_TOKEN`, both visible to all repositories.
Registration is not credential-validity or registry-ownership proof. Complete
the minimal owner contract and CO adapter independently, then integrate exact
revisions; do not require the whole foundation or publish an unmerged candidate.

### Streaming admission reproduction, 2026-09-09

An independent installed-package HTTP probe revises the initial source-only
hypothesis: invalid empty `user` and array-valued `routing` each returned 400,
with zero provider calls and zero accepted records. Earlier shared validation
already rejects these inputs; later duplicate validators do not prove unsafe
spend. Retain these cases as guards, not failing regressions.

The valid auto-streaming control returned 200, invoked the observed chat client
once, and retained one admission. That provider call had no active measurement
scope, proving its triage work preceded the acceptance clock. Installed
`server.py` SHA-256
`a28fd4aaafb3852315d0b69541ab12235c6cdcd6c75b5ceff7d8f1c5ff08e08a`
matches candidate `bbe7eae1a24a95e17b5933ca75cc6b2598f896e4`.
The spy only recorded state, with assertions after the response. This is a
mock-provider unit reproduction over real HTTP, not customer latency evidence.
Repair the valid-stream timing boundary without bypassing existing validation;
see [the reproduction receipt](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1110#issuecomment-5597865731).
The full-suite checkout remained unchanged during this independent probe.

Full regression at `bbe7eae1a24a95e17b5933ca75cc6b2598f896e4` terminated
with **9 failed, 3420 passed, 2 skipped in 794.44 seconds** on local
macOS/Python 3.14. Eight failures exposed compatibility with lightweight
handlers when measurement was disabled; one workflow contract required the
existing standalone benchmark import spelling. Repair
`0b10b553ab916f341ddfbb5c1fc6989c23e0f293` keeps the unmeasured acquisition,
release, and disconnect paths independent of measurement state and restores
the explicit import. The failed-file plus receipt regression passed **55 tests
in 10.92 seconds**. A transient indentation error during repair caused collection
failure and was corrected before that run; it does not replace the original RCA.
Full regression on the repaired final head and hosted Linux acceptance remain
required, along with the valid-stream timing and typed-error accounting repairs.

Integrated candidate `3b6dd47ebb0f88802bacdd302051d2f03e7d5003` preserves
#1105 trusted SSE identities and includes valid-stream triage in admission time.
An actual HTTP rejection after authorized triage reproduced `unfinished`; the
shared error adapter now classifies pending admitted failures without replacing
acknowledged, capacity, cancellation or write-failure outcomes. Focused local
verification: **83 passed in 35.72s**. Independently installed exact-head wheels:
**33 passed in 14.21s**, with disjoint package manifests and imports verified
outside the checkout. Full regression is still pending; no hosted, deployed or
customer-KPI success follows from these local receipts.

The [response-process follow-up](doctoring/irt_router_measurement_review.md#response-process-identification-follow-up)
adds a lawfully redistributable 2017 perspective and a predecision-covariate
comparison proposal. Its source figure was inspected in the actual browser.
Observed-data calibration and an immutable owner estimation contract remain
unverified; latency correlation cannot substitute for those acceptance gates.

Full regression for `3b6dd47ebb0f88802bacdd302051d2f03e7d5003` is now
terminal: **3442 passed, 2 skipped in 771.43s** on macOS/Python 3.14.
This supersedes the pending observation above, not the separate hosted/release
gates. An independent installed-wheel HTTP probe exposed pre-capacity triage
in auto chat streaming; Responses streaming and nonstreaming chat passed the
same saturated-slot controls. Preserve the green regression as historical
evidence and repair the uncovered case, as specified in
[the runbook](doctoring/autonomous_kpi_runbook.md#integrated-receipt-regression-and-remaining-capacity-defect-2026-09-09).

Next accuracy gap, independently reproduced against installed candidate
`c7345670e08f029ad3aa5dd1133037bb4b451d9b`: a successful real HTTP route
request retains one admission receipt and one workflow result, but neither
record exposes an explicit durable link to the other's identity. The receipt
has `request_id`; the workflow has `workflow_run_id` and `owner_id` only.
Field-level equality assertions fail; this mock-provider probe does not claim
observed customer accuracy. A separately stacked successor must bind trusted
request identity to outcomes without treating cache reuse as a new execution
or discarding requests that fail before producing a workflow.

The bounded tracked-data audit at `53a9266a639361651064d7748fa74b396dd493ef`
found no qualifying observed-accuracy cohort. The NIM manifest contains authored
tasks, historical benchmark reports contain aggregates, and Noema incidents
select failed deliveries rather than a complete request window. These cannot
supply the existing customer KPI. Require permitted-use provenance, a complete
bounded ingress window, independent outcome adjudication and exact model/policy
revisions before the first observed baseline. The linkage successor prepares
that measurement; it does not itself establish its correctness or improvement.

Capacity repair `c7345670e08f029ad3aa5dd1133037bb4b451d9b` now has terminal
local full-suite evidence: **3452 passed, 2 skipped in 753.15s** (macOS,
Python 3.14; execution 39067). Its isolated installed-wheel receipt and SSE
identity slice passed **43 tests in 17.88s**. Independent saturated-capacity
HTTP probes confirm zero classifier/provider calls with measurement enabled
and disabled. These results do not establish hosted checks, protected merge,
publication or customer accuracy.

The separate linkage successor `4cf7feafd554fbbd65dfc3b790f1081623b0d05a`
retains focused passing evidence, but its first full-suite attempt (28355)
terminated during collection: missing `hypothesis`, exit 2 after 5.41s.
This is an incomplete test environment, not a passing full regression. Repair
the successor's isolated test dependencies without changing the base candidate's
installed-wheel environment, then rerun against a frozen documented checkpoint.

The capacity candidate is now [PR #1112](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1112),
head `c7345670e08f029ad3aa5dd1133037bb4b451d9b`, stacked on #1108 at
`129a665016ed1acd79ae12915c905b1020856fcc`. Security run
[34327884508](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34327884508)
was admitted with three queued jobs. The review list is empty. CodeRabbit's
SUCCESS status is explicitly a
[skipped review](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1112#issuecomment-5598554823)
because its automatic reviews exclude non-default target branches; it is not
approval. Canonical review coordination received this finding. No merge or
deployment follows from the page's “Able to merge” indicator.

Bounded visual inspection: opened the actual PR in the browser and directly
viewed its 1265 × 712 English screenshot. The title wraps onto two lines;
branch labels, Scope heading and opening provenance paragraph remain readable
without overlap in the inspected viewport. Lower sections require scrolling
and were not visually audited. This is a PR-document inspection, not product
UI, responsive, locale or Figma acceptance.

The linkage successor at `af8d732e6cfc9c0169ac850f875f42f1db7eecd4`
completed its frozen local full suite: **3462 passed, 2 skipped in 822.68s**,
exit 0 (execution 81304). This supersedes the collection-only failure above:
a separate locked project environment supplied the missing test dependency,
without changing the base candidate's wheel environment. The run used successor
Python source and the unchanged base native extension, so dedicated successor
wheel acceptance remains separate and in progress. See the successor's
`docs/doctoring/workflow_request_link.md` for exact reproduction and failure
history. No observed accuracy baseline, protected merge or release is established.

Research follow-up [now records](doctoring/measured-routing-evidence.md#multilevel-follow-up-source-2026-09-09)
the read scope and proposed applicability conditions for Jin et al. (2022),
including independent review and direct inspection of PDF page 7. The remaining
work is an owner-validated observation/estimand contract and dependence-aware
held-out evaluation, not production adoption based on a literature citation.

Linkage delivery checkpoint: [PR #1113](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1113)
now stacks frozen `af8d732e6cfc9c0169ac850f875f42f1db7eecd4` on #1112.
Dedicated noneditable wheel acceptance completed **53 tests in 26.39s**;
root independently verified disjoint archive members, both installed import
origins and the original real-HTTP request/outcome join probe. The PR preserves
artifact hashes and the missing-Setuptools and macOS path-alias probe failures.
Hosted run [34329594602](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34329594602)
has three queued jobs, not acceptance. Review, protected delivery and batch
submission-to-item lineage remain open.

Hosted #1112 checkpoint: Security run 34327884508 is now terminal **SUCCESS**
across all three jobs. Job 102389289972 checked out merge
`aca87f45839f7d03956cc4e37f9646ff2dadbbab` (head `c7345670`, base `129a6650`)
on Linux/Python 3.12.14: **3452 passed, 2 skipped in 760.25s**, then 134
benchmark/docstring checks and 40 installed-wheel checks passed. This supplies
hosted-platform evidence previously pending; it does not establish independent
approval, protected-main merge, registry publication or customer KPI improvement.

Next batch gap: isolated test `387aa2111142b13b327f7065226c0f22c305b872`
reproduced successful HTTP submission/retrieval of two items but no durable
submission-request association after SQLite reopen (one failed in 3.75s).
Candidate `369ea1e34dd0f4b3da9672ceae068656af6a69a8` passed 65 focused
checks in 16.51s after repairing association persistence, redundant registry
writes and response-only registry-write diagnostics. This is not full or
installed-package acceptance and no batch PR has been submitted.

Independent review still found a recovery gap: a remotely accepted job can
return its handle after registry-write failure, yet later retrieval is unavailable.
Recovery must use an owner-bound, expiring backend descriptor and exact item
identities; a naked remote handle must never bypass ownership. Preserve absent
usage and distinguish remote acceptance, association commit, registry persistence
and actual recoverability. A status-only response does not complete this gap.
The new work remains isolated from the tested #1112/#1113 candidates.

### Research-stack integration checkpoint — 2026-09-12

The earlier stacked-PR receipts above are historical evidence, not proof that
their changes reached protected main. Main `012beaacd0631f8cd3391c77744eeb626269b5de`
lacked the retained research ancestry; no deletion from main was established.
Ordinary merge `52fd0da99224f0889e8b012667a93940f6a324ee` preserves that
ancestry and current main behavior. The test synchronization repair at
`36af4a56` waits for actual receipt finalization, without inventing response
delivery or moving its timestamp.

Frozen integration `81ad64cf77a49f7bc2a57f4851a5c3259387ce5d` completed
**3,688 passed, 2 skipped in 261.42s**, terminal session 90461. This is source
testing with a separately installed native namespace, not installed-core,
hosted, release or observed-customer acceptance. The accuracy and latency
targets remain unmeasured; the next gap is protected delivery of complete
request/outcome evidence and independent held-out evaluation.
See [the integration runbook](doctoring/kpi_stack_integration.md) for lineage,
the original failure, its reproduction and remaining acceptance work.

Visual inspection: the runbook at `0fd408aa` was rendered at
`http://127.0.0.1:18766/` in a real browser, English, 1265 × 712. Two screenshots
were directly opened in the task: the top and the verification/acceptance
section after scrolling. Text, revision identifiers and headings were readable
without horizontal clipping or overlap in those views. The viewport edge cut
off continuing vertical content normally; the final paragraph was not inspected.
This is a local document preview, not Figma, product UI, mobile or locale
acceptance; screenshots remain in the task tool output, not repository assets.

Research intake: [LaRT measurement review](doctoring/lart_measurement_review.md)
separates token-length evidence from wall-clock decision latency and
full-data fitted references from known true parameters. The proposed
fast-mlsirm-owned calibration experiment remains unimplemented and unmeasured;
it does not change routing defaults or close the observed-outcome gap.

Cache aggregation follow-up: frozen `4bc96045037d04fa7477a1532c75f99f0d7e9898`
repairs repeated/mixed cache items losing initial-decision timing or masking
failure within one HTTP admission. Full source: **3,699 passed, 2 skipped**;
separate installed core/native: **82 passed**. These are correctness receipts,
not observed accuracy or latency improvement. See the
[single integration runbook](doctoring/kpi_stack_integration.md#request-level-cache-aggregation-repair--2026-09-12)
for RED evidence, hashes and reproduction. Central Noema dispatch acceptance
still lacks receiver/run proof; its exact owner evidence is recorded there.
Do not substitute a successful event submission or old-head Security result
for current-head independent review, protected delivery or release.

### Existing gateway repair not adopted by the review sidecar — 2026-09-12

The [transport comparison receipt](doctoring/review_phase_transport_comparison.md)
connects central run `34688188671` / job `103539568718` to source pin
`414f22973658c4ddc3d4320fcf7acd9b4e8ba991`. That source fails the eligible-free
final-synthesis transport regression. Existing protected merge
`9334dc91aaf853b758077e983517a822b6b21edb` passes the same selected regression,
13 bootstrap tests, and the exact central `68daf0f` import/startup contract.
The dependency lock is byte-identical. This is an adoption gap for the central
workflow owner, not justification for duplicate CO fallback code or consumer
retries. The original incident's terminal role remains uncorrelated; do not
claim this defect is its sole cause.

Next evidence: central protected pin adoption, current-head mandatory reviews
and checks, then a real successful review with immutable runtime identity.
Until then this gap stays open. Local loopback/test-double success does not
establish provider recovery, release, observed accuracy, or decision-latency
improvement. Test commit `8065ada1` remains preserved on its diagnostic branch;
this research-PR update imports documentation only and does not claim that
test is already part of its own CI suite.

The historical overall-deadline recommendation above is superseded by the
user's model-specific timeout policy: no common application/agent/gateway
deadline by default. Provider termination, explicit user cancellation and
configured per-model administrative timeout must remain distinguishable.

### Retrospective calibration intake: split identity remains open

The [pinned LaRT matrix audit](doctoring/lart_measurement_review.md#pinned-matrix-identity-audit)
records actual public-data identity checks, not an estimator result. The
published row split places 21 of 28 evaluation rows alongside a training row
with the same suffix-derived base-model identifier. Its 100 item columns have
only 40 distinct labels. These observations rule out treating that split as
independent base-model generalization or joining items by raw labels alone.

The next owner experiment must freeze benchmark-qualified item identities,
reviewed base-model groups and separate family lineage, then fit only on
training observations. Compare paired held-out Brier score/log loss at equal
observation budgets; record excluded populations and unavailable generation
failures explicitly. Released fast-mlsirm contracts remain the estimator
boundary. Public matrices do not supply CO decision timestamps or known true
latent parameters, so neither decision-p95 nor true-parameter RMSE can be
claimed from this retrospective experiment. Data rights, grouping verification,
owner implementation and observed gains remain open; no route default changes.

Preprocessing follow-ups now live in [Draft successor PR #1139](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1139)
at `0024522146803627b8741470ebefaf79ffa4a310`, preserving the complete prior
delta before this normal document revert. The [handoff](doctoring/lart_measurement_review.md#preprocessing-evidence-successor)
keeps the upstream Draft/maintainer-approval boundary and unverified estimator,
rights, accuracy and latency gates visible. This is not gap closure or release.

The [combined-item and preprocessing follow-up](doctoring/lart_measurement_review.md#predictive-application-preprocessing-follow-up)
now verifies the benchmark-qualified retained-cell mapping against all eight
pinned source matrices. Correctness matches in all 12,800 cells; combined
length values are individually shifted by one in all 12,800 cells. The pinned
predictive loader adds another one before held-out log transformation.
Freeze the intended offset and test preprocessing sensitivity before adopting
its results. This narrows the item-identity gap but does not resolve model
family lineage, dataset rights, estimator validation or measured customer gain.

`.github`-hosted PRs' `noema-review`/dispatch runs succeed in that historical
observation). The earlier proposed universal deadline is superseded by the
explicit model-timeout requirement: model execution defaults to null, and only
an administrator-configured model limit may bound its complete execution.
Readiness probes have a separate finite operational contract. The old run does
not prove current deployment behavior or justify imposing a global inference cap.

### Read-only timeout policy visibility — local, not runtime activation

Source `6774dab4` exposes an admin-only timeout-policy GET that separates fresh
configured seconds/revision from the local serving snapshot. It reports seconds
and `enforcement_available=false`; reads do not activate limits or refresh
routing. The actual HTTP and related pool/policy/security checks pass 88 tests
in 9.52 seconds. Source `f9505a5c` adds model-scoped audit history with stable
older-revision cursors and at most 100 records per read; 96 related tests pass
in 7.70 seconds, including HTTP authorization and invalid-bound checks. HTTP
set/clear/restore, released Rust runtime integration and actual administrator
UI acceptance remain open. See
[policy evidence](doctoring/model-timeout-policy-evidence.md#read-only-operator-policy-view).

### Unknown request outcome — local error-contract repair

At `76d1caab`, a passthrough timeout or connection failure with unknown
acceptance no longer escapes as a generic internal error. The existing
single-attempt/no-fallback decision is retained, with a caller-safe
`provider_outcome_unknown` response, `retryable=false` and an explicit
SDK no-retry header. No tool execution is inferred from a model timeout.
OpenAI SDK 2.54.0 → actual loopback HTTP → orchestrator → mock provider
verifies one primary call, no fallback, and no raw diagnostic disclosure.
The SDK-enabled related run passes 212 tests in 14.63 seconds. This is
local evidence, not a protected release or live-provider result; full-suite
verification of these new commits remains pending. Higher-level Strix
retries, SSE errors, default-null full-response lifetime and UI acceptance
remain open. See [incident and SDK evidence](doctoring/model-timeout-policy-evidence.md).

The separate Naruon Noema 429 incident lacks per-attempt upstream status;
final gateway status alone cannot establish every candidate's failure cause.
Local `0b949aa2` adds bounded numeric status to the existing common failed-
attempt log without reading provider text or bodies (89 related tests pass,
15.28 seconds). Full verification and release of this diagnostic addition
remain pending; provider availability itself is not repaired by better logs.

### Tool-loop-emitting-agent routing — 2026-09-13

Paper fidelity gap (Fugu report arXiv:2606.21228 §3; Fugu-Ultra Conductor):
the paper routes a tool loop back to the agent that emitted the tool call,
but this gateway previously ranked a follow-up carrying `role: "tool"`
results like any new request under a virtual selector (`orchestrator/free`,
`orchestrator/auto`, `contextual-orchestrator`), so a different
provider/model could receive tool results for calls it never emitted — an
id-format and behavior mismatch across NIM/OpenRouter/OpenCode models, and a
real failure mode for the `noema` and `opencode` reviewers (org CI) that use
tools through this gateway.

Local repair: `TaskOrchestrator` now keeps a bounded, thread-safe
`tool_loop_memory` map (`tool_call_id -> emitting agent id`, LRU-bounded by
`tool_loop_memory_max_entries`, default 4096 — a memory bound, not a product
limit) recorded whenever a served response carries `tool_calls` on
`proxy_completion`'s single-agent passthrough, `route_once`, `conduct`'s
worker step, and `_orchestrated_provider_completion`'s structured synthesis.
The last of these generalizes to both of its callers and both provider
surfaces: the Responses API's `function_call` items (keyed by `call_id`,
adapted into the same `{"id": ...}` shape `_record_tool_loop_agents` already
consumes from chat's `tool_calls`) and `response_format`-only chat
passthrough's `tool_calls`. `_apply_tool_loop_route` moves a follow-up's
remembered emitting agent to the front of the already-fully-filtered
candidate order only when it is still eligible under the request's own
constraints (an explicit concrete model is never overridden; free/ZDR scope
and circuit-breaker state are re-checked), falling back to the normal order
otherwise. On the Responses surface, no separate follow-up lookup was
needed: `_orchestrated_provider_completion` already converts `input` to
chat-shaped messages before candidate selection, and that conversion already
turns a `function_call_output` item into a `role: "tool"` /
`tool_call_id: call_id` message, so `_apply_tool_loop_route`'s existing chat
lookup covers it unchanged. Served responses carry
`orchestration.tool_loop_route` (`"emitting_agent"`/`"fallback"`) and
`orchestration.tool_loop_agent_id` as evidence on every one of these paths.
Nine targeted tests in `tests/test_passthrough_provider_failover.py` cover:
routing to the emitting agent over a higher-ranked one, falling back when
the emitting agent's circuit is open, explicit-concrete-model precedence
(on both `proxy_completion` and the Responses structured-synthesis path),
free-model precedence (never returns to a non-free emitting agent), LRU
eviction, a Responses `function_call` recording the serving agent, a
Responses `function_call_output` follow-up returning to it, and a
`response_format`-only chat passthrough follow-up returning to it; the
touched suite plus `tests/test_api_contract.py`, `tests/test_self_check.py`,
and `tests/test_tool_execution_fallback.py` pass locally (192 passed, 4
known pre-existing local-only failures from the openai SDK version pin
mismatch — 2.44.0 installed vs. the locked 2.54.0 — unrelated to this
change); `python -m interrogate` reports 100% docstring coverage unchanged.
A live-traffic/consumer-adoption result from `noema` or `opencode` remains
open and is not established by this local test evidence.

### Message-count provenance registry — 2026-09-14

Issue #1157 (shared-context accounting) required provider/model-specific
counting provenance instead of a raw-text heuristic standing in for message
accounting. #927 explicitly left prompt sizing for future work and #1151 is
the separate common-output-ceiling concern; neither is reopened here. PR
#1178 (`feat/context-window-candidate-filter`, not merged) added a raw-text
*lower bound* for selection-time candidate filtering — deliberately a lower
bound, not message accounting, and left untouched by this change.

`contextual_orchestrator/token_counting.py` gained
`COUNTING_PROVENANCE_REGISTRY`, keyed by exact model identifier, each entry
citing an official source (currently the OpenAI Cookbook's "How to count
tokens with tiktoken", fetched live 2026-09-14) and scoped to exactly the
model identifiers that source states the framing constants apply to —
`gpt-3.5-turbo-0125`, `gpt-4-0314`, `gpt-4-32k-0314`, `gpt-4-0613`,
`gpt-4-32k-0613`, `gpt-4o-mini-2024-07-18`, `gpt-4o-2024-08-06`. Bare family
aliases (`gpt-4o`, `gpt-4`, ...) are deliberately excluded: the source itself
calls its formula for those "an estimate, not a timeless guarantee," and
registering them would reintroduce exactly the heuristic framing constant
operating rules 3.1/9.1 prohibit. `NativeExactTokenCounter.describe_messages`
/`count_messages` return an exact, provenance-bound count only inside that
scope; a `tools` payload, a non-text content part, or any other field outside
`role`/`content`/`name` raises `TokenCountUnavailable` naming the field, and a
model outside the scope raises the same way. Tools, image/audio content,
`instructions`, and prior Responses-API `response_id`/conversation references
remain explicitly unavailable — no accounting for them is invented.

The served `/v1/chat/completions` response gained an optional
`prompt_count_source` field, set only when
`contextual_orchestrator/server.py::_prompt_count_source` obtains a count for
the exact served request/model from this registry, and omitted otherwise; it
sits next to the existing `usage`/`usage_measurement_status` pair without
touching the candidate-selection surfaces PR #1177/#1178/#1179 are changing.

Remaining gap: tool-schema, multimodal, `instructions`, and prior-response
token accounting have no verified official source yet, so #1157's shared-
context budgeting (using the count against a model's valid output ceiling and
remaining input/output context) is not implemented by this change — it is a
provenance-registry foundation, not a closing fix. Local evidence only: the
new and touched tests pass (`tests/test_token_counting_boundaries.py`,
`tests/test_api_contract.py`, `tests/test_self_check.py`), and the full
`tests/` run is green apart from the pre-existing, unrelated local-only
`openai` SDK 2.54.0-pin and `mcp.Client` failures already tracked elsewhere in
this document.

### Shared-context output budgeting — second half of #1157

Building on the counting-provenance registry above, `token_counting.py`
gained `shared_context_output_budget(agent, messages, requested_output_tokens,
*, counter, tools=None)`. It returns a `SharedContextBudget` decision (never
an estimate) only when every input is authoritative: `agent.context_window`
is a known positive int, `agent.max_output_tokens` is known, and
`describe_message_count` returns an exact, registry-verified count for
`messages`/`agent.model` (no tools, no non-text fields, an in-scope model).
Any other case — unknown context window, unknown output ceiling, or a count
unavailable because of tools/modality/an out-of-scope model — returns `None`
so callers leave existing behavior untouched; per operating rule 9.1, no
fixed ratio or hidden shrinkage is ever substituted. When a decision is
returned, `remaining = context_window - prompt_tokens` (the exact count
already folds in the model's reply-priming tokens per the OpenAI Cookbook
framing, so they are not subtracted twice) and `output_ceiling =
min(max_output_tokens, remaining)`.

`ModelClient.chat()` applies this decision at the exact site the existing
catalog output-ceiling clamp already ran (`effective_max_output_tokens`,
before the provider HTTP call): with no explicit caller/client output budget,
it now sends `min(max_output_tokens, remaining)` instead of the bare catalog
ceiling; when the caller's own explicit budget exceeds `remaining`, or
`remaining < 1` regardless of an explicit budget, it raises the existing
`ProviderRequestTooLargeError` (413, `request_too_large`) naming
`context_window`, `prompt_tokens`, and the requested budget — never a silent
clamp or truncation. `ModelClient` gained an optional `token_counter`
constructor argument (the default `TaskOrchestrator` wires its own counter
into its default client only; a caller-supplied client keeps whichever
counter it already has) and `take_shared_context_budget()`, mirroring the
existing `take_usage()` thread-local seam. The served
`/v1/chat/completions` response gained an optional `shared_context_budget`
evidence object (`context_window`/`prompt_tokens`/`output_ceiling`/
`source: "exact"`) next to `prompt_count_source`, read and cleared by
`server._take_shared_context_budget()`, and omitted when no decision was
made.

Scope left out of this step, by design: only the non-streaming
`ModelClient.chat()` send path is wired. The streaming (`_stream_send`) and
local-proxy/passthrough send paths still apply only the pre-existing plain
`_clamp_agent_token_budget` clamp against `agent.max_output_tokens`, with no
shared-context accounting — a natural follow-up once this path is proven.
Tool-schema, multimodal, `instructions`, and prior-response token accounting
remain unavailable inputs (per the registry gap above), so requests carrying
them still fall back to the pre-existing plain clamp with no `#1157` evidence
attached; #1157 is not closed by this change. Local evidence only: the new
and touched tests pass (`tests/test_token_counting_boundaries.py`,
`tests/test_output_budget_model_max.py`,
`tests/test_prompt_count_source_http_honesty.py`, `tests/test_api_contract.py`,
`tests/test_self_check.py`), `python -m interrogate -v contextual_orchestrator/`
reports 100%, and the full `tests/` run is green apart from the same
pre-existing, unrelated local-only `openai` SDK 2.54.0-pin and `mcp.Client`
failures tracked elsewhere in this document.

### Streaming and passthrough shared-context output budgeting — closes the above follow-up

The streaming/local-proxy gap left above is now closed. `ModelClient._stream_send`
applies the identical `shared_context_output_budget` decision at the exact
site its own plain `_clamp_agent_token_budget` clamp already ran (using the
same "explicit" seam as `chat()` — the request-scoped or client-level
`max_output_tokens`, never whatever catalog default `stream_chat()` already
wrote into `payload["max_tokens"]` before calling `_stream_send`) — before
any provider bytes are sent for that attempt. `ModelClient._proxy_send`
(behind `proxy_send`/`proxy_send_once`/`probe_structured_chat`, the transport
under the server's single-agent tool-loop passthrough) applies the same
decision for the `chat/completions` endpoint, reading the caller's own
`max_tokens` from the untouched passthrough body *before* the existing
local-provider default-cap injection runs in the same method, so a
gateway-injected local default is never misread as the caller's own explicit
budget. In both cases: no explicit budget and all inputs authoritative sends
`min(max_output_tokens, remaining)`; an explicit budget over `remaining`, or
`remaining < 1` regardless of an explicit budget, raises the existing
`ProviderRequestTooLargeError` naming `context_window`, `prompt_tokens`, and
the requested budget — never a silent clamp. `shared_context_output_budget`
already returns `None` for any shape `describe_message_count` cannot account
for (a Responses-shaped `input` body, `tools`, non-text content, an
out-of-scope model), so passthrough callers get no decision — not a forced
estimate — whenever the caller-shaped body isn't exact chat-message
accounting; this is the smallest-diff outcome the follow-up required, not an
extension of the registry's own scope.

The true streaming `/v1/chat/completions` route
(`server._stream_route_completion`) already flushes SSE response headers and
writes its first (`role: assistant`) frame before ever driving the provider
call, so a rejection on this path necessarily surfaces *after* headers are
committed rather than as a pre-request HTTP error. No new error-frame plumbing
was needed for this: `ProviderRequestTooLargeError` is already a
`ProviderUpstreamError`, and `_stream_route_completion`'s existing
`except ProviderUpstreamError` handler already turns any such upstream
rejection into a terminal SSE error frame carrying the same
`context_window=`/`prompt_tokens=`/`requested_output_tokens=` evidence in its
message. Live evidence: the terminal success ("stop") frame now also carries
the same `shared_context_budget` object as the non-streaming response (same
field name, same shape — `context_window`/`prompt_tokens`/`output_ceiling`/
`source: "exact"`), attached only when `ModelClient.take_shared_context_budget()`
returns one (reusing `server._take_shared_context_budget()` verbatim,
matching this repo's existing pattern of attaching `prompt_count_source`-style
evidence next to a terminal chunk rather than inventing a second shape), and
omitted otherwise.

Left out, and why: the `responses`-endpoint conversion branch inside
`_proxy_send` (used only for local/`opencode_go` providers) is unchanged —
its payload is already a Responses-shaped `input` body, which
`describe_message_count` cannot account for, so wiring it in would only ever
compute `None` there; the batch-upload send path (`_batch_run`) is a separate
async transport (job upload/poll, not a live per-request send) and stays on
the plain catalog clamp; embeddings (`_send_raw` called from
`embed_with_usage`) never carry chat messages and are untouched. The
passthrough response body itself is deliberately left with no
`shared_context_budget` field: this transport's own module contract is that
"the full provider response shape... survives verbatim" for tool-loop
callers, so adding an extra top-level key there would violate that contract;
only the outbound request-shaping decision (send/clamp/reject) applies to
passthrough, not response evidence. Local evidence only: the new and touched
tests pass (`tests/test_true_streaming.py`, `tests/test_output_budget_model_max.py`,
`tests/test_token_counting_boundaries.py`,
`tests/test_prompt_count_source_http_honesty.py`, `tests/test_api_contract.py`,
`tests/test_self_check.py`), `python -m interrogate -v contextual_orchestrator/`
reports 100%, and the full `tests/` run (3723 passed, 2 skipped) is green
apart from the same five pre-existing, unrelated local-only `openai` SDK
2.54.0-pin and `mcp.Client` failures tracked elsewhere in this document.

### Streaming terminal-frame shared-context evidence ordering hazard — fixed

Review of the streaming follow-up above found an ordering hazard it did not
account for: `TaskOrchestrator.stream_route`'s post-stream real-time judge
(`policy.realtime_judge`, on by default; see its "Real-time judging after the
stream" comment) issues its own provider call on the same thread — through
`_model_judge_verification` -> `_FastMLSIJudgeAdapter.complete()` ->
`ModelClient.chat()` — and `chat()` unconditionally clears, and can
repopulate with *its own* evidence, the thread-local shared-context-budget
accessor at entry. `server._stream_route_completion` read that accessor via
`server._take_shared_context_budget()` only after `stream_route` had already
returned, i.e. after the judge's own call had run and potentially overwritten
it — so the terminal SSE frame could carry the judge's `shared_context_budget`
evidence, or none at all, instead of the served request's. This is the same
dishonest-evidence failure mode this document's honest-metrics principle
forbids, just on the streaming success path rather than the accounting
surfaces this document otherwise tracks.

Fixed by capturing the served request's evidence *inside* `stream_route`,
immediately next to the pre-existing `take_usage()` call and before the judge
runs, following the exact pattern already proven for usage: a new optional
`shared_context_budget_callback` parameter (mirroring `usage_callback`'s
shape) hands the caller the evidence at that point. `server
._stream_route_completion` now passes this callback — guarded by an
`inspect.signature`-based duck-typing check so a minimal test double whose
`stream_route` does not accept the parameter still works, falling back to the
old post-hoc `_take_shared_context_budget()` read only in that case — and
uses the captured value for the terminal frame. The non-streaming response
path's `_take_shared_context_budget()` call is unchanged: it already reads
before any judge call runs and was never affected by this hazard.

`prompt_count_source` was audited for the identical hazard and confirmed
safe, not just assumed so: `server._prompt_count_source(orchestrator,
messages, model_name)` derives its answer purely from the request's own
`messages`/`model_name` via the counting-provenance registry, never from any
`ModelClient` thread-local state, and — unlike `shared_context_budget` — it
is not even emitted on the streaming path today, so there is nothing on that
path for a second call to clobber.

New regression coverage:
`tests/test_true_streaming.py::test_http_route_stream_terminal_frame_survives_realtime_judge_second_call`
installs a working (not neutralized) fast-mlsirm judge whose `.judge()` makes
a real second provider call through the adapter, and asserts the terminal
frame still carries the served request's `shared_context_budget`
(`prompt_tokens`/`output_ceiling`), not the judge's. Verified to fail against
the pre-fix code — the terminal frame carried the judge's own
`prompt_tokens`/`output_ceiling` instead of the served request's — before the
fix landed. Local evidence: `tests/test_true_streaming.py`,
`tests/test_output_budget_model_max.py`,
`tests/test_prompt_count_source_http_honesty.py`,
`tests/test_token_counting_boundaries.py`, `tests/test_api_contract.py`, and
`tests/test_self_check.py` all pass, and `python -m interrogate -v
contextual_orchestrator/` reports 100%.
## 2026-09-13 constant-only KPI PR repair findings

Exact-source review found that [PR #1125](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1125)
at `dbfcc0c17177af0339f1b326f3584db866d8a943` only declares
`ROUTE_DECISION_LATENCY_FIELD`; its test checks the constant's existence/value,
not a measured trace interval. [PR #1126](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1126)
at `2ecc4a03ffe30707d9ce69ae3448e9f83a50e312` does the same for
`REQUEST_OUTCOME_ASSOCIATIONS_FIELD`, without exercising an authorized export.
Both tests describe runtime behavior they do not actually assert. Passing them
cannot establish decision latency, outcome linkage, or customer KPI acceptance.

Keep both Draft PRs open as repair findings. Reconcile their proposed public
field names with the canonical request measurement/export owner before any
successor claims complete inheritance. Existing receipt timing is nanoseconds
and request-scoped; do not copy it onto per-step traces or reinterpret total
generation latency as decision time. Acceptance needs real HTTP requests,
durable acknowledgement and missing-value checks, plus authorized one-to-many
request/outcome joins retaining unfinished requests and excluding other owners.
PR #1138 is an export candidate, not proof that either legacy field contract
has already been adopted. No predecessor closure or production change follows
from this audit.

## 2026-08-31 OpenRouter is a normal, routable provider again

Supersedes the 2026-08-30 entry above's characterization of `evidence_only=True`
on `openrouter` (commit `952996ec`) as settled ZDR hardening: that
characterization was false, as the entry above now records. On direct review
this pass, "ZDR eligibility is grounds to block a whole provider account"
turns out to be backwards -- ZDR is a route/model-level property, never a
provider-account-level one. `PROVIDER_MODEL_SOURCES`'s `openrouter` entry no
longer sets `evidence_only=True`. Concretely this fixes two bugs at once:

1. **`orchestrator/free` structural emptiness (ADR 0041's own finding).**
   OpenRouter is the one provider source with genuinely reliable native
   pricing/`is_free` evidence; excluding it from serving regardless of that
   evidence directly caused the "structurally empty in practice" state ADR
   0041 documented. OpenRouter can now serve like any other discovered
   provider.
2. **A backwards ZDR-evidence exclusion.** `_apply_discovered_model_evidence`
   computed `zdr_capable=not model.evidence_only and matches(...)`, which
   meant OpenRouter's own rows could never be marked ZDR-capable even when
   they exactly matched OpenRouter's own declared ZDR feed
   (`https://openrouter.ai/api/v1/endpoints/zdr`). That exclusion is gone;
   OpenRouter's own matching rows are now credited exactly like every other
   provider's.

**What is preserved, not removed**: the underlying reason a "provider-neutral,
not OpenRouter-only" evidence-application contract was insisted on during
PR #901's review (matching model ids from OpenRouter's feed onto *other*
providers' discovered rows, not just OpenRouter's own) is completely
untouched -- `_apply_discovered_model_evidence` still applies evidence to
every provider's rows identically; OpenRouter's own rows simply stop being
the one arbitrary exception to that rule.

**The genuine technical risk this raises, and how it is closed**: OpenRouter
can multiplex one model id across several backing providers, so a
discovery-time ZDR feed snapshot proves a route *was* attested when fetched,
not which provider serves a *later* request. Client-side endpoint tracking
to predict this would only be as reliable as the last snapshot. Instead,
`ModelClient` now applies OpenRouter's own documented request-time
enforcement -- `"provider": {"zdr": true}` in the request body
(https://openrouter.ai/docs/features/provider-routing) -- via
`_pin_openrouter_zdr`, called from every wire-level transport an OpenRouter
agent can reach under an active `zdr_only` request scope: `_send` (the
`route`/`conduct` chat path), `_stream_send` (SSE streaming), and
`_send_raw` (the tools/structured-output passthrough path both
`proxy_send` and `proxy_send_once` funnel through), plus `proxy_send_bytes`
(binary speech responses whose request body is still JSON). This is OpenRouter's own
server-side enforcement for the request being sent right now, not a
client-side prediction — strictly stronger than what discovery-time
filtering could ever guarantee.

**The asynchronous Batch API path is pinned too**: `_batch_run` (JSONL file
upload then a separate `/batches` job) does not go through the three
transport functions above, but it independently calls `_pin_openrouter_zdr`
on each request body it serializes into the uploaded JSONL, so a `zdr_only`
batch request against OpenRouter gets the same `"provider": {"zdr": true}`
enforcement as the synchronous paths.

Embedding Batch JSONL follows the same contract. After `zdr_only` resolves an
attested OpenRouter embedding agent, `CostRoutingCoordinator` records the
provider-routing pin on each `EmbeddingBatchRequest`; its JSONL body emits
`"provider": {"zdr": true}` without exposing the internal `zdr_only` field.

Verified: `tests/test_orchestrator_client_boundaries.py` adds direct unit
coverage of `_pin_openrouter_zdr` (no-op outside `zdr_only`, no-op for
non-OpenRouter agents, adds/merges the pin correctly) plus wiring-verification
tests on `_send`/`_stream_send`/`_send_raw`/`_batch_run` that capture the actual
outgoing JSON body. `tests/test_model_discovery.py`,
`tests/test_auto_discovery_server.py`, and `tests/test_review_gateway.py`
were updated where they asserted the old, now-reversed
`openrouter` + `evidence_only=True` behavior; the general `evidence_only`
mechanism itself (for any future provider that might legitimately need it)
is untouched and still tested, just no longer applied to OpenRouter by
default. Full suite green; `interrogate` 100% on the touched modules.

### GAP RESOLVED ON PR HEAD — 2026-08-31: model groups, free discovery, and measured capacity

[PR #971](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/971)
implementation parent `a36770179a695b3825a0fc2ca45eace09b5e3b8f` implements the
requested provider-neutral contract. The live PR head must be read from GitHub
because this baseline commit necessarily advances it.

- Routing identity is an exact `model_group`; provider-family grouping is not
  part of the serving contract. Collision-resistant group ids preserve model
  punctuation rather than conflating distinct upstream model names.
- Authenticated OpenRouter discovery admits concrete zero-price models and
  excludes the aggregate `openrouter/free` router from serving candidates.
  ZDR evidence is evaluated per discovered model rather than disabling the
  entire OpenRouter account.
- Discovery, ZDR lookup, provider policy/credit reads, inference, and racing
  default to no fixed wall-clock timeout.
- The measured group ledger reports observed peak RPM and TPM from real
  completed requests; missing token usage remains missing rather than being
  invented.
- Bytez's discovery parser and `Key` authentication path are implemented. The
  observed Bytez HTTP 500 remains upstream/account evidence, not proof that the
  provider should be silently excluded.

Verification on the current PR working tree:
local full suite `2913 passed, 1 skipped`; the no-fixed-timeout revert-focused
suite passed `15 passed, 1 skipped`. Hosted Security, unit, fuzz, OpenCode,
Noema, and Strix checks for exact head
`39c80927f89c1f1f955f42af0b9d1f14b1527b70` are queued, so earlier-head hosted
success is not current-head merge evidence. Therefore this remains verified
PR-head behavior, not yet protected-main or deployed evidence. Central
`.github` PR #1546 merged as `5686de41660d51a7a7f22b8840dfa6ccfe5ff3f1`,
delivering the shared no-timeout, independent-Noema, stacked-PR, and exact-head
review fixes; a fresh central scheduler run has been dispatched for this PR and
is waiting for a GitHub-hosted runner.

## 2026-09-02 canonical immutable release + resumable long-running execution — cross-repo consumer evidence (keyverse#132, EgressWeave#235)

**Observed gap (owner-lane, `contextual-orchestrator`).** Fresh consumer evidence surfaced on PR #971 (`ContextualWisdomLab/keyverse#132`, migrating its hourly model-backed workflow to `orchestrator/free`): this repository has no GitHub `latest` release endpoint (`/releases/latest` returns 404), so a consumer that wants a durable, pinnable contract has no choice but to vendor/pin a raw source revision (currently `464da4715b495b5eaaa593eba3796e2d976ee0c9`). That violates the org-wide CWL boundary convention documented in `ContextualWisdomLab/.github`'s `docs/CWL-MASTER-CONTEXT.md` §7 (this repository has no local copy of that doc): a consumer must consume a released API/client/schema contract, not a mutable sibling source commit. `CLAUDE.md`'s own commands section already documents "Semantic Versioning where the repository publishes a release" as the intended model; today nothing publishes one.

**Observed gap (owner-lane, runtime).** The same comment reports Keyverse inherits `OPENCODE_RUN_TIMEOUT_SECONDS=2100` and that `EgressWeave#235` independently hit a 45-minute Actions job timeout around the same gateway-backed OpenCode pattern. Both are consumer-side leaf wall-clock wrappers reappearing around the org's `timeout=null` model-inference contract (this repository's own `docs/planning/adrs/0032-model-group-cost-aware-discovery.md`: "Model inference has no fixed wall-clock timeout") because this repository has never supplied the owner-side alternative: a way for a long-running (hours-scale) `orchestrator/free` request to survive a host/runner-level execution boundary without being misclassified as a model failure, and a way for an interrupted maintenance execution to resume/re-dispatch from a checkpoint instead of restarting or serializing the hourly lane forever. Every leaf keeps re-inventing its own timeout because the owner has not yet drawn the line between "the model is slow" (never a failure) and "the execution environment ended" (an infrastructure/admin/user-cancellation event with its own terminal state).

**Why this is owner-lane, not per-consumer.** Per the org-wide CWL boundary convention (`ContextualWisdomLab/.github`'s `docs/CWL-MASTER-CONTEXT.md` §7): a boundary gap common to multiple consumers is fixed at the canonical owner, never duplicated/worked around per leaf. Two independent consumers (Keyverse, EgressWeave) hitting the identical class of gap in the same window is exactly the "genuine common demand" signal that rules out excluding this as consumer-specific.

**Scoped action items (tracked here, not yet started as of this entry).**
1. *Canonical immutable release.* Publish a tagged, versioned GitHub Release for `contextual-orchestrator` (SemVer, per `CLAUDE.md`'s already-stated intent) with an immutable client/API/schema surface consumers can pin via `/releases/latest` instead of a source SHA. No paid/provider-specific fallback should be required to consume it.
2. *Resumable long-running execution.* A dedicated ADR (this is architecturally significant, not a leaf fix) defining: explicit, distinguishable terminal states for user cancellation, provider termination, audited admin timeout, and infrastructure/runner loss; and a checkpoint/exact-head re-dispatch mechanism so an interrupted maintenance execution resumes rather than restarting from zero or blocking the hourly lane indefinitely. Must preserve the existing `timeout=null` inference contract — this is explicitly not a return to a sidecar-wide fixed deadline.

**Owner RED/GREEN acceptance (as stated by the repository owner).** A long-lived `orchestrator/free` request survives beyond the former leaf timeout without synthetic model failure; explicit user cancellation/provider termination/audited admin timeout/infrastructure loss remain distinguishable; an interrupted maintenance execution can resume/re-dispatch with exact-head/checkpoint identity; the resulting released API/client/schema is immutable enough for consumers to pin without vendoring this repository's source.

**Relationship to already-tracked items above.** This extends, with concrete cross-repo evidence, the "hourly-loop durable/resumable execution boundary" item already deferred out of PR #971 (the narrower job-timeout piece of that item is tracked separately in PR #1027). The immutable-release item is new to this baseline.

The separate Naruon Noema 429 incident lacks per-attempt upstream status;
final gateway status alone cannot establish every candidate's failure cause.
Local `0b949aa2` adds bounded numeric status to the existing common failed-
attempt log without reading provider text or bodies (89 related tests pass,
15.28 seconds). Full verification and release of this diagnostic addition
remain pending; provider availability itself is not repaired by better logs.

## 2026-09-14 Durable job registry opt-in degraded silently

`build_job_registry` returned the same non-durable `JobRegistryFactory(None)`
for two different states: no `batch_job_registry_valkey_url` configured, and a
configured URL whose `redis` client (the `queue` extra) is not installed. The
module docstring justified the fallback as "nothing changes for deployments
that have not opted in", but the same branch also fired for deployments that
*had* opted in, where everything changes — job registries stop surviving a
restart, which is the failure this module exists to prevent — with no warning,
log, or readiness signal to distinguish the two.

Fixed by logging a warning naming the credential and the `queue` extra when a
URL is configured and the client is missing, matching the established pattern
elsewhere in the repository (`telemetry.py`'s OpenTelemetry warning, the
`__main__` fast-mlsirm probe's `reason: missing_dependency`, and the judge's
explicit fail-closed reason). The behaviour is deliberately not changed to a
hard failure: a serving gateway should not fail startup over an optional extra.
Verified RED against unfixed product code, then GREEN, in
`tests/test_batch_job_registry_boundaries.py`
(`test_configured_url_without_redis_package_warns_about_lost_durability` plus
`test_unconfigured_registry_stays_silent`, which proves the never-opted-in path
stays quiet).

Not established: whether any deployment currently runs in this state. The
readiness surface still does not report registry durability; that would be a
separate change.

### Typed streaming fallback attempt evidence and route contract docs — 2026-09-14

Addresses issue #1016 rows 2 and 4 (remaining gaps confirmed on the 2026-09-13
assessment; row 1 is separately handled by PR #1171 and is untouched here).
Row 2: the single-worker streaming fallback trace step (`TaskOrchestrator.
stream_route`, `contextual_orchestrator/orchestrator.py`) previously recorded a
failed candidate as prose only (`"subtask": "Failed direct route attempt
(streamed)"`), unlike the structured-synthesis candidate loop's typed
`route.attempted[]` entries (`_orchestrated_provider_completion`). Each failed
streaming attempt now also carries `outcome` (`retryable_transport`,
`request_too_large`, `deadline_exceeded`, `fail_closed`), `error_code`,
`provider_status`, `retryable`, and `transport`, built by one small shared
helper (`_typed_attempt_entry`) both paths now call; `deadline_exceeded` reuses
PR #1053's `model_timeout` error code rather than a second vocabulary. Prose
(`subtask`, and a new `reason` field) remains for humans but is no longer the
only signal. Row 4: the previously internal, undocumented `route`/
`attempted[]` shape is now a versioned contract
(`OrchestrationRoute`/`OrchestrationRouteAttempt`, `api_contract.py` spec
`0.3.0`), and `tests/test_api_contract.py` validates both a real
structured-synthesis failover and a real streaming failover against it (11
tests: `test_api_contract.py`, `test_true_streaming.py`). Local run:
`python -m pytest tests/test_api_contract.py tests/test_true_streaming.py
tests/test_stream_error_identity.py tests/test_provider_error_taxonomy.py
tests/test_model_timeout_policy.py tests/test_self_check.py -q` — 109 passed.
`python -m interrogate -v contextual_orchestrator/` — 100%. Not addressed:
issue #1016 row 1 (separate PR), and the SSE wire frames themselves still omit
`orchestration.route` per-token (only the persisted/queried workflow-run trace
carries it) — no caller currently reads it from the streaming wire response,
so this was left out of scope rather than silently assumed equivalent.
### Sqlite connection lifecycle warnings — test hygiene, not a product defect — 2026-09-14

Issue #1168's residual `ResourceWarning: unclosed database in <sqlite3.Connection ...>`
warnings (56 of 2044 total on `767e67fb`, `python -m pytest tests -q -W default
--ignore=tests/fuzz`) were root-caused by opening `-W error::ResourceWarning` on
each named file in isolation. `_AgentPoolStore` (`contextual_orchestrator/orchestrator.py:3511`)
already opens and closes a short-lived connection at every one of its five call
sites via `try`/`finally`; `_StateStore` (`orchestrator.py:4168`) already exposes
`close()` for its long-lived `self._conn`, and `TaskOrchestrator.close()`
(`orchestrator.py:4556`) already calls into both owned stores. No product code
was leaking. The leaks were entirely test-owned:

- `with sqlite3.connect(path) as connection:` in `tests/test_model_timeout_policy.py`
  (14 sites); `tests/test_agent_pool_db.py` (13 sites) already closed on this
  restack base via main's `closing(...)` form — the sqlite3 connection
  context manager only commits/rolls back the open transaction on exit, it does
  not close the connection, so every one of these leaked.
- Bare `connection = sqlite3.connect(...)` with no `close()` at all in
  `tests/test_metering.py` (7 sites) and `tests/test_cost_ledger_boundaries.py`
  (1 site, not in the original 56/6-file count but the same defect).
- `TaskOrchestrator([...], state_db=...)` constructed twice and never closed in
  `tests/test_structured_output_distinct_fallback.py` — the owning `_StateStore`
  connection could only be closed by the orchestrator's own `close()`, which the
  test never called.

`ResourceWarning` fires lazily at garbage collection, so pytest's per-test
attribution (e.g. the KPI evidence's "line ~3880 in `_save_in_transaction`", or
this fix's own residual runs attributing warnings to `test_healthz_is_unauthenticated_and_ok`)
names whatever test happened to be running when the GC swept the leaked
connection, not the test that created it — a red herring worth recording so it
is not re-chased.

Fix: closed every leaking connection deterministically — `contextlib.closing(...)`
wrapping the `with ... as` sites (preserving the original transaction semantics
via a second `with connection:` inside), `try`/`finally` around the bare
`sqlite3.connect()` sites, and `orchestrator.close()` (`try`/`finally`) around
both `TaskOrchestrator(state_db=...)` instances in the structured-output-fallback
test. No production code changed.

`tests/test_cost_ledger.py` was explicitly left untouched: it is covered by the
separate `test/cost-ledger-sqlite-close-1168` branch (PR #1173), which is **not**
merged into this branch's `origin/main` base (`1af542bb`, post-#1030/#1177/#1180 restack) despite being widely
believed already landed — `git merge-base --is-ancestor dc8f4d81 HEAD` returns
false on this base. Its ~20 unclosed-database warnings remain on this branch
until that PR merges.

Before: `python -m pytest tests -q -W default --ignore=tests/fuzz` → 2044
warnings, 56 `ResourceWarning: unclosed database`. After (this fix alone, on
top of the same unmerged `test_cost_ledger.py`): 2008 warnings, 20 remaining
`unclosed database` warnings — all attributable to the still-unmerged
`test_cost_ledger.py` fix. Once PR #1173 merges, the count drops to 0. Full
suite: 3663 passed, 1 skipped, 5 known local-only failures (the openai SDK
2.54.0-pin tests and the `mcp.Client` privacy test), unchanged by this change.
`python -m interrogate -v contextual_orchestrator/` remains 100% (no production
code touched).

## 2026-09-14 Generated-plan step bound origin (section 3.1 / 5.1 fidelity)

`OrchestrationPolicy.max_workflow_steps = 6` bounded generated Conductor plans
(prompt text and parser) without stating where the number came from, while the
Fugu-Ultra report's "up to 5 steps" (arXiv:2606.21228 S3.2.3) is a training
setting that must not be copied into other layers. This change records the
origin as a product decision beside the field and in `docs/architecture.md`,
keeps the value administrator-owned through `OrchestrationPolicy`, and adds
`tests/test_paper_contracts.py::test_generated_plan_bound_comes_from_policy`
(prompt and parser follow the policy value; default stays 6). Not established:
an ablation of the bound itself, which belongs to the #568 equal-budget lane.
