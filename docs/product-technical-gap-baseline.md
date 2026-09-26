Warning: truncated output (original token count: 137107)
Total output lines: 7240

# Contextual Orchestrator: Product & Technical Gap Baseline

## 2026-09-26 protected-main test-signal recovery — Proposed

Canonical owner PR [#1266](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1266)
recovers the runtime and test authority lost by earlier restack merges. Its exact
CI-equivalent baseline exposed 153 failures plus one collection error on
protected `main@5665b0ad`; the first owner repair removes 77 OpenRouter
availability/answer-quality violations and restores collection so remaining
failures are visible rather than hidden.

The existing RED
`test_unbounded_synchronous_embedding_waits_for_provider_completion` proves
that the application default `timeout=None` reached
`ProviderEmbeddingBatchBackend.wait`, where `math.isfinite(None)` raised
`TypeError` instead of waiting for provider completion. GREEN
`343bf7f82fd4f483ca829295c735b4e75017e31c` accepts `None` and non-finite
numeric deadlines as the same explicit unbounded contract; documentation
successor `ea1ac223bd8eb8c137c490ef7871734a27558a69` records that boundary.
This is source evidence only until fresh exact-head hosted tests execute.

Hosted RED run [36147466940](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/36147466940)
selected the repository's pinned Rust 1.97.1 directory override, whose
`profile = "minimal"` omitted `rustfmt` and `clippy`; the Rust gate therefore
failed before formatting or linting. GREEN source
`6e70a196d715fd3c9ba9b89bc8698f252ead04e5` declares both components in
`rust-toolchain.toml`. This is configuration evidence only until its fresh
exact-head hosted Rust gate completes.

Follow-up source at `f882ee7b12e805bd5924a28d3a23999d7e76f160`
integrates the previously dropped #1074 request-policy/effort snapshots,
psychometric deployment identities and selection-design receipts; restores typed
EgressWeave allowlist failures; repairs the planning ADR filename and paper
inventory; and moves affected CI installs to the exact `uv.lock` environment.
These source deltas supersede the earlier “not fixed” bucket descriptions; their
hosted verification remains pending.

Current-head review found the OpenRouter telemetry fetch still used unbounded
`response.read()`. RED `e76d3b3954de37c293a98339aefadbdd016e0d90`
read the full oversized payload (requested size `-1`) and returned a parsed
99.5 value. GREEN `9cf335ab8021923cf4e301f951e4e37a5bae01fb`
reads only the shared 8 MiB provider-response bound plus one byte and rejects an
oversized payload before JSON parsing. Exact source/test AST parsing passed; the
direct behavior probe rejected the oversized response with one 65-byte read
under a test-injected 64-byte bound and preserved a valid 99.5 response.

Status remains **Proposed**. Fresh exact-head hosted tests, independent approval,
protected integration, an immutable fast-mlsirm release instead of VCS
consumption, and consumer pins remain unverified.

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
actionlint and diff-check also passed. New hosted run `34318012080` was queued
at the latest observation. Neither the historical full-suite result nor focused
success proves current-head hosted completion, independent approval, or release.

At `035b58c252cd4f4a79e712d028e8265264326c94`, the repository-owned
Security and Quality workflow filters pull requests to `main`. PR #1108 targets
another PR branch, so its zero check-run count is consistent with this trigger
exclusion, not a successful Security run. The repair removes the base filter
without changing job permissions or switching to privileged `pull_request_target`.
It also keys cancellation by workflow, repository, and PR number. Central review
and security ownership is unchanged; this does not repair or replace their gates.

The regression assertion failed on the old filter. After repair, the new contract
and existing benchmark workflow contracts passed (9 tests), and actionlint emitted
no findings. An initial test collection failed because PyYAML is not installed;
the test instead uses the existing stdlib text-contract pattern, with actionlint
checking YAML syntax. No dependency was added. A new synchronize event must still
demonstrate hosted execution on the actual stacked merge revision. Trigger syntax
and local tests alone are not that execution evidence. GitHub documents that PR
branch filters match the [target branch](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

## 2026-09-09 Integrated rollback regression receipt

PR #1108 at `fbb933cbcaa1f1695c6cc305657f450f22b3be4c` includes the
non-force base integration and transaction rollback repair. Its clean, pinned
worktree completed the full local suite: **3,399 passed, 2 skipped in 823.46
seconds**, exit 0. The focused persistence, workflow-object authorization, and
governance checks separately passed **30 tests in 10.06 seconds**. The full log
is `/tmp/co-rollback-integrated-fbb933cb.log` on the validation host; it is a
local receipt, not a hosted artifact or release attestation. At the subsequent
GitHub check, this exact head had **zero check runs and zero reviews**. Status
contexts alone do not satisfy the Security job or independent review gates;
protected merge and release remain unverified.

The analytics specification at `ddf087da136dbb5f2110aba6db20dd9bd384db7c`
was opened in the actual browser and its screenshots directly inspected at
1265 × 712, English locale. The opening context and autonomous-target table
were readable; the table's three columns and three rows had no overlap or
horizontal clipping in that view. Images are inline in the validation task,
linked by [the PR inspection receipt](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1107#issuecomment-5596505419).
This is bounded document evidence, not responsive, multilingual, Figma, or
product-interaction verification. No customer accuracy or latency gain follows
from either receipt.

## 2026-09-09 Decision-latency durable acknowledgement gap

[Issue #1110](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1110)
tracks the accepted-request-to-durable-decision interval required by
[the analytics specification](analytics_spec.md). At
`b2c09930a8d335952e4f4d8de5371460cb14fcd6`, `route_once` still times the upstream
invocation, not that interval. `conduct` persists a completed workflow after
generation. Neither is a measured initial-decision receipt.

The existing state store has synchronous `durable=True` writes and best-effort
queued stream writes. Reuse that owner; a successful queue operation, a later
flush-on-read, or an audit append without configured storage is not a durable
acknowledgement. Three retention tests now explicitly exercise the synchronous
path. An additional test prevents background draining and verifies committed
records through an independent SQLite connection before any store read.
All 19 persistence tests passed in 7.19 seconds. An in-memory mutation forcing
asynchronous writes fails the new assertion. This proves commit visibility in
the tested SQLite configuration, not power-loss survival or customer latency.

Next implementation must connect validated admission, selection completion and
successful commit acknowledgement within one monotonic clock domain; distinguish
initial/failover decisions and retain failed/unfinished requests in accounting.
PR #1108 owns transaction rollback repair and remains open; its valid delta must
be retained during integration. No measured p95 or accuracy improvement is yet
established, and no production routing default changes follow from these tests.

## 2026-09-09 LSIRM model-selection source reconciliation

At source `1b31166024a20b5ab5be6547a0cfd95a7099a7f1`, direct visual inspection
of the NSF-hosted Springer-formatted LSIRM PDF confirmed the same mixture/event
description discrepancy previously found in arXiv v2. The
[version-specific receipt](doctoring/measured-routing-evidence.md#lsirm-identification-and-version-discrepancy-2026-09-09)
records the PDF hash and inspected page. Before publishing a model-selection
contract, fast-mlsirm must reconcile the decision event and prior parameterization
against the current publisher copy and supplementary implementation. CO must
not copy the ambiguous threshold into routing or count this investigation as
an accuracy improvement. No current fast-mlsirm implementation defect has been
demonstrated by this source comparison.

## 2026-09-09 Expanded-population validity research gap

At source `479bfe7e096832e1711c4d99b59621a66c3a2f59`, the research inventory
was extended with ETS RM-19-07 and a bounded read receipt. The
[proposed evaluation design](doctoring/autonomous_kpi_runbook.md#expanded-population-validity-proposal)
separates item DIF, scale linking, and observed routing accuracy. CO owns
evaluation context and outcome collection; fast-mlsirm remains the numerical
owner. Released diagnostic-contract availability, observed-data support by
language/domain/model revision, and any accuracy or latency gain remain
unverified. This is a research proposal, not a production gate already shipped.

## 2026-09-09 Benchmark prior interpretation gap

At `ef374defdf4037a829d4b4d6d61c5a8b314e8c05`,
`contextual_orchestrator/benchmark_priors.py` labels an equal-weight composite
of median/MAD-normalized Arena and Quality Index scores as a measured success
probability. Inspection of the cited Chatbot Arena v1 metadata and sections 3–4
does not justify that cross-instrument calibration. The docstrings now identify
the legacy heuristic and correct the paper's author list; runtime behavior is
unchanged. Outstanding work: authenticate archived rating snapshots, define
the target outcome and model-version mapping, fit/calibrate against observed
held-out tasks in the numerical owner, and validate accuracy/decision latency
before protected adoption. A bounded score and constant prior mass do not prove
measurement validity. No customer KPI gain is claimed.

## 2026-09-09 Paper inventory consistency

`34bf2f3f5925a84630edfccaf608e06f5e3192ae` removes a stale blanket
redistribution assurance that contradicted the version-specific license audit.
All five stored PDF fingerprints verify, but publisher-byte equivalence and
additional redistribution rights remain unverified. Browser inspection of this
revision could not proceed because the Mac was locked; no visual pass is claimed.
See the [runbook evidence](doctoring/autonomous_kpi_runbook.md).

## 2026-09-09 Numerical candidate and rendered KPI evidence

The [autonomous KPI runbook](doctoring/autonomous_kpi_runbook.md) records a
completed owner baseline scoring-filtered run (41 passed, 1 ignored), finite-case
bitwise cross-version parity, and an unfavorable candidate unit p95. The candidate
remains experimental: candidate scoring-filtered tests now pass (42 passed,
1 ignored), but full-suite tests, observed customer outcomes, durable
decision timing, protected release, and consumer adoption are not established.
The exact-revision KPI table received a partial desktop screenshot inspection;
this does not complete responsive, multilingual, or product UI verification.

The live REST PR inventory still includes correction PR #1043 at
`05fe7178c12f37206458e256e468f498e9a5ce20`. Its proposed correction supersedes
the historical blanket `_invoke` deadline recommendation below in intent, but
is not merged evidence. Current policy remains default-null model timeouts;
do not implement the historical overall-cap recommendation. Keep #1043's delta
in its owner PR rather than duplicating its patch in this research branch.

## 2026-09-09 Autoresearch loop: KPI baseline, #1075 closure evidence, main-protection blocker

Loop branch `autoresearch/20260909-kpi-loop` (code+tests identical to
`origin/main@414f2297`; branch diff is docs-only). KPI baseline: **85 open
PRs** (`gh pr list --state open`, lower-is-better toward 0 via merge or
verified-successor full-delta inheritance only; no force-push, no close
without evidence).

- **Issue #1075 (nim_benchmark 100% branch coverage): gap already closed.**
  The issue's exact gate block passes on unmodified code: 134 passed,
  `nim_benchmark.py 1205 stmts / 436 branches / 0 miss / 0 partial = 100%`
  (coverage 7.15.0, `--fail-under=100` exit 0), no `pragma: no cover` in the
  module. Former gaps `434`, `645`, branch `671->682` are covered by
  `EqualBudgetModelClient` + `_BudgetDelegate` cases (including `usage=None`)
  in `tests/test_nim_benchmark_release_acceptance.py` that landed after filing
  (e.g. `7ba5fefc`, `a080297d`). Evidence comment posted on #1075; issue left
  open for owner close. No code change (experiment 1: discard, unit evidence).
- **Issue #1079 (main branch protection): owner-action blocker confirmed live.**
  Protection still requires stale `Hypothesis property tests`,
  `Atheris coverage-guided`, `CodeQL analysis`, `Python supply chain`
  (API-verified); every post-#1054 PR to `main` is unmergeable via protection
  (e.g. #1094 `MERGEABLE` but `BLOCKED`). Not bypassed; documented for owner.
- **PR #1094 RCA:** `opencode-review` failure is reviewer-verdict wait, not a
  code defect. The wait does not stop independent work.
- **Mergeable path:** non-main-base stacked PRs (e.g. #1104→#1101:
  `MERGEABLE`/`CLEAN`, core checks green) but Draft — no readiness flip
  attempted (owner process boundary).

## 2026-09-09 Autonomous KPI targets and verified unit execution

`docs/analytics_spec.md` now sets an observed delivered-correct improvement
target of at least one percentage point and decision p95 at most 20 ms with
at least 10% reduction, subject to stated uncertainty and non-regression gates.
These are selected targets, not results. The
[single experiment runbook](doctoring/autonomous_kpi_runbook.md) records owner
boundaries, isolated contract bootstrapping, and reproducible commands.
AGENTS.md and CLAUDE.md link to it; the existing hourly automation was updated
without adding a duplicate. PR #1067 exact head
`84a6052369a7bf8b6faae5db475bb68a5ad54a91` passed all 51 focused routing and
benchmark-boundary tests in 744.99 seconds on a heavily loaded host. No customer
accuracy, decision p95, full-suite, protected merge, or deployment follows from
that unit result.

## 2026-09-09 Existing research attribution repaired

Audit of `279f7e03` found an incorrect Jeon et al. title/DOI in
[measured routing evidence](doctoring/measured-routing-evidence.md), plus claims
that per-member ledgers prevent atomistic fallacy and JSON structure establishes
judge reliability. The corrected citation identifies the latent-space
item–respondent interaction model; the mapping now separates ledger arithmetic,
schema validation, and unverified psychometric validity. This removes unsupported
research justification without changing runtime policy. A calibrated observed
task evaluation and released owner diagnostics remain required.

## 2026-09-09 Response-time research and measurement gap

The [psychometric review](doctoring/irt_router_measurement_review.md#response-time-research-extension-2026-09-09)
now traces van der Linden's hierarchical speed/accuracy framework to a visually
inspected earlier report and the final publication's DOI. It records a proposed
joint-model experiment, not evidence that fast responses imply high ability.
CO decision overhead and provider completion duration require separate clocks
and denominators. Observed-data availability, released owner support, baseline
accuracy, and routing-decision p95 remain unverified; no production default
change or measured improvement is justified by this literature extension.

## 2026-09-09 Review gateway failure and existing timeout repair

PR #1103 at `4776a970ed8bdef3406684aef84952740b476d88` has a terminal
Noema 502 after 926 seconds. Its gateway bootstrap used CO `414f2297`,
whose transport default is 90 seconds. Artifact attribution and the remaining
causal uncertainty are recorded in
[the incident investigation](doctoring/noema_gateway_failure_20260909.md).
The existing repair owner is PR #1053 at
`76c047585f54fcbe940fe168412f51627d3f79dd`, still Draft, with failures in all
three CodeQL compatibility analyses on inspection. Older test claims in its
description do not validate this head. Next work is repair and verification in
#1053, followed by release and consumer adoption; no runtime recovery or buyer
accuracy/decision-latency improvement is established by these observations.

The linked central scan run `34122498232` reached status publication, where
Python job `101756437515` received HTTP 403 with both configured credential
paths. Current `opencode-agent` installation `141441800` covers all repos but
has only `statuses: read` and `actions: read`; the app registration owned by
`anomalyco` also requests only those read permissions. Central publisher
identity/permission repair is required before validating the consumer gates.
No missing-secret claim or successful-scan claim follows from this evidence.

## 2026-09-08 Psychometrics evidence boundary: research trace added

PR #1103 head `19448d95` adds APA 7 references and implementation constraints
from Messick (validity arguments), Embretson and Reise (item information and
identification), and Reise et al. (fit versus interpretation). These sources
extend the IRT-Router review without claiming a production accuracy gain:
buyer accuracy still requires observed outcomes, declared sampling and failure
denominators, and uncertainty; route latency still requires request/decision
timestamps and its own denominators. The new head is awaiting hosted checks and
independent approval.

## 2026-09-08 IRT interpretation gap: reviewed, not measured improvement

Against source head `c648797dfbec58dbdce60f35ed6dc5b356953387`, the
[IRT-Router measurement review](doctoring/irt_router_measurement_review.md)
records publisher-page visual inspection and a coordinate-identification
constraint relevant to the proposed parameter RMSE KPI in PR #1103.
Prediction fit, parameter recovery, and observed buyer accuracy remain separate
claims. No new estimator, production policy, or measured accuracy/latency gain
is delivered by this review. Next acceptance requires released owner diagnostics,
identified parameter-recovery tests, and observed-task evidence under the
analytics specification; existing matrix-shape validation is insufficient.

The linked review now includes a standalone Rust documentation test. On
2026-09-08, `rustdoc --test docs/doctoring/irt_router_measurement_review.md`
with rustdoc 1.97.1 passed one synthetic unit example: original and transformed
inner products both equal 3.5 while unaligned coordinate RMSE equals 1.0.
This demonstrates the identification pitfall, not estimator accuracy or a
latency improvement. It is a manual documentation check, not yet a hosted
CI gate or a test of the released fast-mlsirm implementation.

## 2026-09-12 timeout owner reconciliation and unknown-outcome safety

PR #1053's valid default-null timeout and administrator-policy delta was 169
commits behind protected `main@012beaacd0631f8cd3391c77744eeb626269b5de`
and conflicted in five files. A non-force merge preserves both histories. The
RED merge-result regression had seven failures: ambiguous transport exceptions
were typed as `provider_outcome_unknown` on one path without updating circuit
evidence, while newer tests expected the older retryable
`provider_connection_error`; the concrete-model HTTP path leaked the raw
exception into a retrying 500 response. The reconciled contract records the
candidate and group failure once, returns non-retryable
`provider_outcome_unknown`, omits provider-controlled diagnostics, and emits
`x-should-retry: false` for both concrete and virtual passthrough. The focused
timeout, passthrough, telemetry, policy, pool, and admin suite passes 287 tests.
Protected-main reconciliation also exposed a duplicate DNS preflight in the NIM
benchmark evaluation adapter: the pinned benchmark transport was never reached,
so 180 evaluation cells collapsed into local failures after capability probing.
The adapter now keeps URL and KV credential validation while delegating address
resolution exclusively to its pinned transport; the malformed-evaluation
contract again fails before artifact publication. Four focused regression and
stale-contract tests pass; five additional adapter tests cover the delegated,
valid injected, unsafe-URL, and missing-credential boundaries. Pytest's
asynchronous fixture-loop scope is now
explicit rather than inherited from a deprecated plugin default.

Five review-discovered timeout paths are also repaired on the same Proposed
successor. Finite model policies now create one monotonic deadline before local
admission and spend the remaining budget on connection, retries, and every
stream read. A timeout caused by that explicit policy returns non-retryable
`model_timeout`; a connection reset remains the distinct non-replayable
`provider_outcome_unknown`. A local admission expiry occurs before any send and
therefore moves directly to an eligible sibling without consuming the
same-agent retry budget. Synchronous embeddings resolve the selected embedding
agent's timeout instead of the client-wide default. Policy writes and OpenAPI
now reject values above the socket-safe 2,147,483,647-second maximum. Focused
tests cover post-send no-replay, streaming lifetime, pre-send failover,
embedding selection, and the numeric boundary.

The reconciled tree's local full suite reports `3686 passed, 3 skipped, 1
deselected`; the deselected owner-contract test requires the released
`fast-mlsirm` native extension, while this runner has neither that artifact nor
a Rust toolchain. Public-object docstring coverage is 100%, Ruff and compileall
are clean. Aggregate branch-aware coverage is 94%, so no full-repository 100%
coverage claim is made and the PR remains Proposed pending hosted exact-head
evidence.

This remains Proposed exact-tree evidence. Protected merge, immutable release,
consumer pin update, and a live `orchestrator/free` recovery remain required.
The triggering `.github` #2106 model gates therefore remain nonpassing even
though its exact-head CodeQL run has subsequently settled successfully.

## 2026-09-07 per-model serving timeout and HTTP policy writes

PR #1053 now applies an administrator-owned `model_timeout_seconds` value on
the selected model's serving path. The client default remains null. There is
no shared application ceiling. Authenticated timeout-only PATCH writes are
admitted and recorded with the opaque principal digest. GET
`timeout_policy` still reports a stale serving snapshot when another process
wrote the durable row; that cross-process refresh remains open. HTTP restore
and administrator UI remain unfinished. This is local regression evidence,
not a protected merge or live-provider recovery claim.

## 2026-09-07 timeout audit visibility repair

On PR #1053 base `1ccc9599415096433214cd9ad0df611eddfc8fbb`, successful
timeout set, clear, and restore operations had durable policy history but no
operator audit event. A local regression reproduced the missing events; the
repair adds committed revision references to the existing audit stream.
History GET access now uses the existing durable replay-authorization path.
An authenticated loopback HTTP regression reproduced missing access auditing
and now checks both successful access and HTTP 503 when audit recording fails.

The timeout-policy and agent-pool suites passed 73 tests in 12.30s before this
documentation update. No live provider, protected merge, or deployment is
claimed. The HTTP test spies on the durable audit call; it does not prove
storage survival after a crash. Policy history remains atomic with the policy
update; the separate operator event is not a new cross-store transaction.
Default-null model timeout and explicit administrator control are unchanged.

## 2026-09-06 model-specific timeout policy: local, not delivered

PR #1053's remote `661ce8db` has a completed 3400-pass/2-skip regression suite
for removing the implicit client timeout. The subsequent local durable-policy
implementation at `439da2e5` has 31 related passes, but does not yet enforce
model-specific execution limits. HTTP write admission and UI controls remain
closed for the new setting. Neither result proves deployment or buyer latency.

A new failure-injection test at `6236e982` demonstrates an unresolved audit
atomicity gap: the update reports an audit error while both memory and a
restarted instance retain the new 7200-second policy. Policy change/history
was subsequently moved into one local pool transaction at `4e839ce1`;
`c3879439` has 37 related passes, including history-insertion rollback for
new/existing rows and rejection of a stale different-value writer. This does
not yet cover authenticated actor evidence or cross-process serving refresh.
Subsequent `d911a38e` adds history-revision comparisons for ABA conflicts;
`e5e9c96f` reads values and revisions in one database snapshot. Their committed
RED cases reproduced stale-value acceptance and mixed revisions respectively;
the latter head has 39 related passes.
Actor evidence is now stored as an optional opaque principal digest at local
`c08a5fd5`; this is not yet authenticated HTTP policy-write E2E and null
historical actors remain unknown. Static-token identity is deployment-scoped.
Local `37bca9ca` adds revision-checked restoration as a new, source-linked
history entry; `62ba3c3b` has 54 related passes including foreign-model and
audit-failure rejection. Authenticated HTTP restore,
precedence, cancellation semantics, released Rust runtime integration and
actual administrator visual/E2E evidence also remain open.

Local `9701dec2` guards ordinary pool saves against stale policy value/revision
overwrites (60 focused passes). `befe04ce` additionally delays removal and
group-change serving publication until durable saves succeed, following three
reproduced failures; 103 related tests passed in 15.34 seconds. Multi-model
batch rollback and cross-process serving refresh remain unproven. Neither
change supplies model deadline enforcement or a new full-suite result.

Subsequent `ad337e18` reproduced partial persistence in all three group/discovery
batch paths when the second model conflicted. `36fc35df` now commits each batch
in one transaction using the existing normalized writes; 122 related tests
passed in 5.04 seconds. Cross-process refresh and end-to-end timeout delivery
remain open; separate bootstrap operations are not one atomic batch.

`a2951f67` adds actual authenticated HTTP evidence: stale ordinary edits fail
without overwriting the other writer's policy, invalid credentials get 401,
and the unfinished timeout write field remains rejected (1 focused pass,
4.01 seconds). This is rejection-boundary evidence, not successful policy
activation or inference enforcement.

See [the evidence record](doctoring/model-timeout-policy-evidence.md) for exact
revisions, retained failures, corrected test-evidence limitations, owner
boundaries and the full remaining acceptance gates. Local configuration work
must not be represented as released enforcement or psychometric accuracy gain.

## 2026-09-12 Optimizer score-domain recovery

Current main `012beaacd0631f8cd3391c77744eeb626269b5de` still accepts NaN,
infinity and out-of-range per-task quality into configuration ranking. Recovery
test commit `40290df6` reproduced 28 failures and 16 valid-case passes (5.89s).
The shared guard at `982b553345623e006698950bd560d94b4038ed33` passed all 76
focused optimizer tests (11.65s), covering both public optimizers and serial/batch
route evaluation. Invalid pairs whose average is valid are rejected individually;
valid endpoints, fractional values and Boolean predicates retain their meaning.

This restores a measurement-integrity prerequisite, not observed accuracy or
latency improvement. Calls finish before score validation; no saved spend or
early cancellation is claimed. Current-head full-suite, installed-package,
independent review, visual inspection and protected-release evidence remain
pending at the initial focused checkpoint. At code/document revision 321409b0,
the full source suite subsequently passed 3645 tests (2 skipped), installed
public-API acceptance passed 44 cases, and desktop documentation was visually
inspected. Protected CI, formal approval, release and real KPI evidence remain
pending. Historical September 9 artifacts do not prove this revision passed.
See [the recovery runbook](doctoring/optimizer_score_recovery.md).

## 2026-09-09 Request-to-provider diagnostic correlation

PR #1105 candidate `f588ca8c093ea7c9a86b857685bfbb1ce3c05fe2` connects HTTP
identity to seven provider diagnostic events and the successful request summary.
The predecessor `7b7b32006e7ae498db2ee781bd423d9c7b6774fc` completed its full
suite with 3399 passed, 2 skipped (1594.26s, exit 0). Follow-up code at
`6b24fe96` passed 81 focused tests, including actual same-socket reuse and
overlapping same-session HTTP requests with two distinct server thread IDs.
The integrated `f588ca8c` suite terminated with 3399 passed, 2 skipped and
1 failure (1767.82s, exit 1): certifi CA loading raised InterruptedError before
the Responses HTTP test could send a request. Same-head isolated HTTP tests
then passed 4/4 in 20.05s. The original failure remains unresolved evidence;
do not infer full-suite success from the isolated pass.

Actual output from all seven provider diagnostic functions at
`7cb97ec8e2979d35b72c86a801ab18f0fd9c213d` was cross-checked with the central
PR #2053 sanitizer at `fc0ab87bfde0900461034be815046914f9019bfc`: trusted IDs
survived, untrusted error-body IDs and text were omitted, and malformed IDs and
embedded newlines were rejected. This isolated contract test does not establish
collector adoption. The later sanitizer `4a0125bf9f50d4d26355249011df03c3735b3abc`
also preserved an actual local GET `/healthz` 200 summary from producer
`f588ca8c`, including its request ID, while rejecting extra detail and an
unapproved path. This supersedes the earlier missing-success-summary limitation
for that route/state only, not every HTTP route. The
[runbook](doctoring/provider_request_correlation.md) records
RED evidence, exact revisions, cleanup tests, and bounded visual inspection.
Not yet established: every orchestration worker path, integrated full-suite and
security gates, protected release, live collector adoption, or customer KPI
improvement. Diagnostic traceability is a prerequisite for attributing failures,
not a substitute for accuracy or decision-latency measurements.

## 2026-09-08 error-response correlation repair

ConceptWeave run 33938445050, job 101256562088, preserves a client-side HTTP
500 with request ID `175d6d59c5294b0e8a21548193b90482`. Its surviving artifact
9969701340 contains gateway stderr but only generic request-failure messages;
it cannot correlate that ID to an internal cause. The job installed CO source
`2e414d15ba58f28597751b625a8a2f00fc9fadcf`. This is not proof of free-pool
exhaustion, a disappeared run, or a currently released fix.

The same correlation gap was reproduced on main
`414f22973658c4ddc3d4320fcf7acd9b4e8ba991`: the common HTTP error response had
a generated ID absent from its log. The proposed repair generates one ID for
both response and warning, prevents detail fields from overriding it, and logs
neither session values nor error details. RED: one missing-correlation failure;
GREEN: 45 telemetry tests passed in 6.58 seconds. This improves future failure
correlation only; it does not recover the historical exception, cover every
streaming-error path, or prove immutable publication or deployed behavior.

## 2026-09-05 PR #1004 mixed provider failure follow-up

At head `2a6b41562114530315bb44d1aa3dede820a68da1`, both `502 → 404` and
`404 → 502` on same-endpoint structured-synthesis candidates returned a
non-retryable missing-model error. The shared exhaustion boundary now preserves
the recorded retryable upstream error first. Caller-selected endpoint, model, free/ZDR,
file-replica, and ambiguous-tool-replay restrictions remain unchanged.
Both ordered regression cases failed before the fix and pass afterward.
See [doctoring](doctoring/provider-diverse-discovery-routing.md#pr-1004-mixed-failure-classification-follow-up).
 Protected merge and post-change live gateway evidence are still required;
head `cdb672c23a23dd3c83be3cd4190f5a7b1d5da032` passed the full local suite
(`3409 passed, 2 skipped in 657.92s`). That result predates the accounting
correction below and does not verify it.

Independent local review reproduced a separate accounting gap: after two grouped
candidates fail, the group ledger records only the final candidate. A prior
failure also hides a later terminal 400 or billed malformed response from the
circuit counter. The proposed correction records both observations at the
actual failed synthesis attempt, before fallback or a budget stop, and removes
the outer duplicate group observation. A later 413 is not a provider failure.
The accounting regressions changed from `7 failed, 11 passed` to `18 passed`;
the wider provider/group/effort/HTTP suite passed all 124 tests. Full-suite and
hosted exact-head evidence for this additional correction must be recorded
separately in the existing PR.
The subsequent response-before-return regression additionally prevents an
unassigned response read or reuse of another candidate's usage. Both cases
failed on `18a29d14`; 178 focused tests pass after the correction. Unknown
usage stays unavailable. The explicitly interrupted full run on `18a29d14`
is excluded from passing evidence; see the same doctoring record.

The next current-head review found that `69b79a6bc2a6039396d6fd03edcac5bef80c686e`
still converted a stale model into an implicit endpoint pin. Existing tests
had preserved that behavior without proving it was required. New cases failed
`12/49` before the shared candidate-list correction; the focused unit/HTTP/usage
suite now passes `52/52`. Virtual AUTO/FREE requests can exhaust each already
eligible model across endpoints; explicit selections and budget enforcement
remain bounded. This is proposed local remediation, not protected or live
acceptance. See the same doctoring record for the corrected contract audit.
An additional eight-case RED on `2582176d` covered malformed-only/mixed-413
exhaustion and pre-return repair failures for virtual and concrete models.
The shared correction preserves the response-failure category and failed-run
usage evidence; all 60 focused cases pass. The interrupted full run on
`2582176d` is not acceptance evidence for this correction.

## 2026-09-02 PR #1004 exact-head structured repair 413 RCA

- **Affected exact head:** predecessor `58c159802d85fe6e8f7b812317560cb1a65133aa` failed writer run `33530310548`, job `99931499707` after `138 passed, 1 failed` in the focused suite.
- **Exact evidence:** `tests/test_model_judge.py::test_structured_repair_does_not_retry_request_excluded_model` established a stale candidate already excluded by a 404, a live candidate producing invalid structured output, and a repair-only 413. The generated handler retired the live candidate and called the generic structured-exhaustion helper, incorrectly raising `StructuredOutputExhaustedError` instead of preserving `ProviderRequestTooLargeError`.
- **Classification:** deterministic code-generation/repair-path defect in this repository, not a provider/network transient, fixture race, missing permission, or expected fail-closed governance result.
- **Causal fix:** keep the repair prompt candidate-bound; on repair-only 413, retire that candidate and start a fresh synthesis only on another already-eligible, non-excluded candidate. If none remains, persist the request-size failure and re-raise the original typed 413. Never retry a request-excluded predecessor.
 - **Verification:** this writer commits only after the focused routing suite, broad suite, compile checks, and `git diff --check` pass. Required exact-head GitHub Checks/reviews still must complete; pending evidence is not treated as passing.

## 2026-09-04 Bytez discovery: filtered empty catalogs and upstream 5xx are distinct fail-closed states

At `origin/main` `60c562de`, an authenticated, bounded live probe loaded only
`BYTEZ_API_KEY` from the operator's local `.env` and emitted no token, response
body, or upstream error text. The earlier `task=chat` HTTP 200 response with an
empty `output` is a successful transport with no usable catalog, whereas an
unfiltered HTTP 500 is an upstream server failure. A fresh probe found the
upstream condition had widened: `chat`, `text-generation`, the other documented
chat-completion-compatible task filters, and the unfiltered request all returned
HTTP 500 with a small JSON object and empty `output`. Raw-token and `Key`-prefixed
authorization produced the same status, so the prefix does not explain the
failure.

The canonical discovery boundary now queries only `task=chat` and then
`task=text-generation`. Bytez documents both as compatible with its OpenAI-style
chat-completions API; audio, image, and video task catalogs are intentionally not
admitted to the ordinary text-chat pool. Discovery never uses the failing
unfiltered endpoint as a fallback. A non-empty filtered catalog is parsed through
the existing Bytez model contract. If both filtered catalogs are empty or fail,
refresh records only task, outcome, model count, and an allowlisted error code;
it retains the durable last-known-good catalog and fails closed when none exists.
The current upstream 5xx therefore remains a first-bootstrap blocker, not a
reason to fabricate usable models.

## 2026-09-14 rate-limit-aware admission for a 429 storm

Production evidence: org CI review lanes call this gateway with
`orchestrator/free`. During a free-pool rate-limit storm every candidate
returned HTTP 429 within ~50ms (noema run 34758641142, strix run 34758679736:
preflight `ready_count: 0`, 7x 429 across OpenRouter and NIM accounts), and the
gateway simply failed the request. `ContextualWisdomLab/.github#2148`
independently root-caused the same failure mode against a private-target ZDR
pool of three OpenRouter `:free` routes on one account, wiped by a single 429
burst; `#2165` shows `noema-review`/`strix` failing closed on the resulting
429/502 with `attempts=1`, blocking unchanged consumer PRs. The owner's
requirement across all three reports is the same: the gateway's job under a
429 storm is to not fail.

Fixed: `orchestrator.py` now parses `Retry-After` (delta-seconds or an
HTTP-date; `provider_errors.parse_retry_after`) and falls back to a numeric
`x-ratelimit-reset*` header when absent, recording a per-agent cooldown
(`TaskOrchestrator._record_rate_limit`/`_rate_limit_remaining`) kept separate
from the health circuit breaker -- a 429 is quota exhaustion, not a model
health failure, and no longer trips `_circuit` (a direct 503 still does).
`classify_provider_failure` now attaches `retry_after_seconds` to any 429/503
classification's `extra_detail`, so both the passthrough transport and the
chat transport used by `_invoke` (route_once/conduct's shared engine) can
record the same cooldown from one `ProviderUpstreamError`.
`_failover_candidates` (shared by every caller, including `route_once`/
`conduct`) now skips a currently cooled-down candidate by default, falling
back to the full list only when every candidate is limited so a caller with no
wait logic of its own still gets one honest attempt.

The wait-then-retry/honest-429 admission decision itself is one shared
implementation, `TaskOrchestrator._await_rate_limit_recovery(candidates, *,
deadline, transport)`: it computes the earliest known cooldown among
currently rate-limited members of `candidates`, waits for it (one bounded
`time.sleep`-backed call, never a busy-loop) and returns `True` when it fits
the remaining budget against `deadline` -- resolved from the request's
administrator-owned `model_timeout_seconds` deadline (issue #1053) when set,
else the new `rate_limit_wait_seconds` constructor/CLI default (30s, a
documented caller-contract bound, not a hidden product limit) -- or raises the
honest `provider_rate_limited` error code (429, `retryable=True`) instead of
misclassifying quota exhaustion as a `502 provider_connection_error` when
waiting is impossible. Two callers reach it:

- `proxy_completion`'s own passthrough failover loop calls it directly each
  round its ranked candidates are exhausted.
- `TaskOrchestrator._invoke_with_rate_limit_recovery` wraps `_invoke` (the one
  shared engine both `route_once` and every `conduct` step, including the
  worker step, call to reach a candidate): when `_invoke`'s own candidate
  exhaustion raises a 429/503 `ProviderUpstreamError` AND every candidate
  currently eligible for that call is rate-limited (a genuine storm, not a
  mixed failure set), it calls the same helper and retries the whole
  `_invoke` call instead of propagating the exhaustion. A mixed failure set
  re-raises exactly as `_invoke` would have, unchanged.

`server.py` answers a raised `provider_rate_limited` error with `429` and a
`Retry-After` header (or the equivalent field in the terminal SSE error frame
when headers are already flushed) regardless of which of the two callers
raised it. `provider_readiness_report` now also reports `rate_limited_until`
and `earliest_ready_seconds` per agent so an external preflight/readiness
sidecar (the org sidecar's own `contextual-orchestrator-preflight.json`
already reports `candidate`/`probed`/`rejected_count` and
`account_skip_after_429` as its RED/GREEN evidence for this class of change)
can wait instead of exiting.

Coverage note: this closes the real `orchestrator/free` HTTP path.
`route_once`/`conduct` (via `_invoke`) is the path CI review lanes actually hit
over `/v1/chat/completions` for a virtual model, since a virtual model with
tools deliberately stays on Fugu route / TRINITY-Conductor conduct rather than
single-agent passthrough
(`tests/test_actions_model_fallback.py::test_http_virtual_free_tools_stay_on_route`);
`proxy_completion`'s own multi-candidate virtual-selector branch remains
reachable over HTTP only through direct API use, but now shares the identical
wait/honest-429 decision through `_await_rate_limit_recovery` rather than a
separate implementation. Every conduct step (thinker/worker/verifier/
synthesizer) shares the one `_invoke`/`_invoke_with_rate_limit_recovery` call
site, so the worker step required by the owner's report gets the fix, and so
do the other roles for free, without a second implementation.

### Follow-up (same day): an omitted cooldown header must still count as cooling

`_record_rate_limit(agent_id, None)` originally returned without recording
anything, so a 429/503 whose provider omitted both `Retry-After` and
`x-ratelimit-reset*` (RFC 9110 10.2.3 permits omitting it entirely; NIM and
OpenRouter routinely do) was never marked cooling -- `_await_rate_limit_recovery`
saw no candidate to wait for and the request failed exactly as if this whole
feature did not exist. The 2026-09-13 production storm may well have been
exactly this shape.

Fixed: an unknown-duration 429 now records the new administrator-owned
`rate_limit_unknown_cooldown_seconds` (constructor/CLI default 5s -- short by
design, so an unknown cooldown is re-probed soon rather than parked) as an
*assumed* cooldown instead of nothing, tagged `cooldown_source: "assumed"` in
both `provider_readiness_report` and the honest-429 error detail (vs
`"provider"` for a real header-derived value); the existing "cooldowns only
extend forward" rule also protects the source label, so a later assumed
cooldown can never shorten or relabel an active provider-stated one.

Two scope refinements, both made after concrete regression evidence rather
than by design intent alone:

- **429 only, not 503.** Extending the assumption to a headerless 503
  made several pre-existing exhaustion tests
  (`test_mixed_failures_surface_the_final_classified_provider_failure`,
  `test_default_mock_endpoint_represents_one_fixture_provider`) loop through
  repeated assumed waits before finally raising the wrong (storm) error
  identity for what was actually a permanent, unrelated failure double. A
  503 ("service unavailable") is a genuine, possibly permanent availability
  signal with no inherent quota-recovery semantics the way a 429 is, so it
  keeps requiring an explicit provider-stated duration to be treated as
  cooling at all.
- **Two or more candidates required (superseded 2026-09-14, see the
  follow-up entry below).** `_await_rate_limit_recovery` at this point in the
  timeline returned `False` (nothing to wait for) whenever fewer than two
  candidates were passed in, regardless of rate-limit state: a "storm" was
  read as implying coordinated failure across a pool of alternatives, and a
  single pinned/named candidate with no failover pool kept its pre-existing
  immediate classified-error contract -- the client already sees
  `retryable=true` and can retry on its own with no server-side latency
  added. Without this guard, `tests/test_provider_error_taxonomy.py::test_chat_completions_returns_openai_compatible_rate_limit_error`
  (one named model, always 429, no headers) hung waiting out an assumed
  cooldown and blew past its 5s client-side read timeout -- the same
  regression shape the coordinator warned the 2026-09-13 storm might be, now
  reproduced directly against a stability-guaranteeing pre-existing test. A
  bug in the initial fix for this guard (`_invoke_with_rate_limit_recovery`
  looping unconditionally regardless of whether the shared helper actually
  found anything to wait for) was caught by the same test and closed by
  checking the helper's return value before retrying. This candidate-count
  threshold was itself later found to be the wrong discriminator: it
  misclassified a virtual selector's pool wiped down to exactly one eligible
  candidate by a 429 (a real, common production shape) identically to a
  genuinely pinned concrete model. See "explicit-vs-virtual selector, not
  candidate count" below for the fix.

Two pre-existing tests in `tests/test_passthrough_provider_failover.py`
(`test_all_candidates_chain_the_last_failure`,
`test_free_virtual_model_never_fails_over_to_a_paid_agent`) used a bare 429
purely incidentally, as a stand-in for "some transient failover-eligible
failure" unrelated to rate-limiting itself, across two real candidates each
(so the two-candidate guard above did not save them); both were switched to
500 to keep their actual intent isolated from this feature.

Tests: `tests/test_rate_limit_aware_admission.py` (20 tests) -- adds a
no-header 429 storm across two candidates that still waits the assumed
cooldown and is served, the same with zero budget returning
429/`provider_rate_limited` with `Retry-After` equal to the ceiled assumed
value and `cooldown_source: "assumed"` in the error detail, and confirmation
that a provider-stated cooldown is never shortened or relabeled by a later
assumed one -- on top of the 17 tests from the entry above.
`python -m pytest tests/test_provider_error_taxonomy.py
tests/test_rate_limit_aware_admission.py tests/test_passthrough_provider_failover.py
-q` passed except the pre-existing local-only `openai` SDK version pin
(`test_sdk_passthrough_unknown_outcome_never_replays`); the repository-wide
suite passed 3704/3705 (1 skipped) with only that same SDK-pin failure and
the separately known local-only `mcp.Client` privacy test failure, neither
touched by this change. `python -m interrogate -v contextual_orchestrator/`
reported 100% docstring coverage.

## 2026-09-14 rate-limit-aware admission: explicit-vs-virtual selector, not candidate count

The "two or more candidates" guard added earlier the same day was itself a
defect, not just a narrow scope choice: `_await_rate_limit_recovery` opened
with `if len(candidates) < 2: return False`, so a pool with exactly one
eligible candidate never waited out a rate-limit storm -- it failed
immediately, which is the behavior this whole feature exists to remove.

Production evidence this case is real and common, not hypothetical:
noema-review run 34772771262 (2026-09-14, sidecar pin `767e67fb`) on
`contextual-orchestrator#1177`: preflight reported `ready_count: 1`, and the
review call then failed after 562s with `HTTP Error 429` served by
`google/gemma-4-31b-it:free`. `ContextualWisdomLab/.github#2148` records that
the private-target ZDR pool is three OpenRouter `:free` routes on a single
account, so one 429 wipes the whole pool and leaves at most one eligible
route.

The guard was added for a good reason that had to be preserved:
`tests/test_provider_error_taxonomy.py::test_chat_completions_returns_openai_compatible_rate_limit_error`
pins ONE named concrete model that always answers 429 with no headers; under
the assumed-cooldown path that test hung past its client-side read timeout.
The correct discriminator was never the candidate count -- it is whether the
caller delegated selection at all: an explicit concrete model must fail fast
with the honest 429 (unchanged), while a virtual selector
(`FREE_MODEL`/`AUTO_MODEL`/`GATEWAY_DEFAULT_MODEL`/no model) must wait even
when only one candidate remains.

Fixed (smallest diff): the count guard was replaced with an explicit-selector
guard. `_await_rate_limit_recovery` gained a required keyword-only
`virtual_selector: bool` parameter; `if len(candidates) < 2: return False`
became `if not virtual_selector: return False`. Both call sites now pass a
value they already compute rather than re-deriving it:
`proxy_completion`'s own passthrough failover loop computes
`virtual_selector = requested_model in {None, GATEWAY_DEFAULT_MODEL,
AUTO_MODEL, FREE_MODEL}` right where `requested_model` is read (the same set
its own explicit-model early-return branch already used inline), and
`_invoke_with_rate_limit_recovery` gained the identical required keyword-only
parameter, threaded in by `route_once` and `conduct`, each of which computes
`model_name in {GATEWAY_DEFAULT_MODEL, AUTO_MODEL, FREE_MODEL}` once from
their own `model_name` parameter. `_invoke_with_rate_limit_recovery`'s own
"not a genuine storm" guard changed from `len(candidates) < 2 or any(...)` to
`not virtual_selector or any(...)`, preserving the untouched "some eligible
candidate is not rate-limited -- a mixed, unrelated failure" branch.

Tests added to `tests/test_rate_limit_aware_admission.py`: a virtual selector
(`FREE_MODEL`) with exactly ONE eligible candidate that answers 429 with
`Retry-After: 1` then succeeds on retry waits once and is served (the single
candidate is called twice); the same single-candidate virtual case with no
wait budget returns an honest 429/`provider_rate_limited` with
`Retry-After`, not a generic failure; an explicit concrete model with a
single candidate that always 429s fails fast with no wait (the injected
sleep hook is asserted never called). Every pre-existing test in that file
stays green, and
`tests/test_provider_error_taxonomy.py::test_chat_completions_returns_openai_compatible_rate_limit_error`
was re-run to confirm the original client-timeout regression does not
return.

`python -m pytest tests/test_rate_limit_aware_admission.py
tests/test_provider_error_taxonomy.py tests/test_passthrough_provider_failover.py
tests/test_provider_reliability.py tests/test_api_contract.py
tests/test_self_check.py -q` passed except the pre-existing local-only
`openai` SDK version pin and the separately known local-only `mcp.Client`
privacy test, neither touched by this change. `python -m interrogate -v
contextual_orchestrator/` reported 100% docstring coverage.

## 2026-09-02 PR #971: main-merge conflict resolution, remaining ThreadPoolExecutor shutdown-blocks, and a verified false positive

Observation time: 2026-09-02 Asia/Seoul, later the same day as the entries
below. Closes out the rest of today's #971 session: the branch's actual
`main`-merge conflict (a real divergence, not the shallow-clone false alarm
noted in an earlier pass), the two remaining `ThreadPoolExecutor`-atexit-join
instances of the root cause already fixed twice below (this file's own
"unbounded per-model OS thread allocation" and "shared discovery metadata
fetches" entries), a raw-`Future` regression that root-cause fix itself
introduced, a shutdown-contract hardening on the new `_DaemonWorkerPool`
primitive, and an external self-fix proposal traced and confirmed non-causal
before being left unapplied. Every claim below is independently re-verified
against `git log`/`git show` on the actual branch history and current-head
source rather than restated from a hand-off.

### Merge-conflict resolution: `main` -> branch, `mergeable_state` `dirty` -> `blocked`

GitHub's `mergeable_state` for #971 was genuinely `dirty` -- confirmed by a
real trial merge, not the shallow-clone false alarm noted in an earlier pass
this same day. Root cause: `main`'s `0db4e5a7` ("fix(review): remove
heuristic candidate cap and ranking") dropped the `max_agents` parameter from
`review_gateway.py`'s `build_review_orchestrator`/CLI entirely as part of
moving admission to evidence-only (no cap, no ranking), while this branch's
own `tests/test_review_gateway.py` still carried tests written against the
pre-removal API and threaded `max_agents=` through several fixtures
(`test_build_review_orchestrator_routes_to_cheapest_selected_agent`,
`test_build_review_orchestrator_uses_model_group_diversity`,
`test_build_review_orchestrator_rejects_invalid_agent_limit`,
`test_main_rejects_invalid_agent_limit_without_traceback`) -- both sides had
independently rewritten the same test file since the PR's base diverged.

Resolved via the standard recipe: `git fetch origin main`, `git merge
origin/main` (merge commit `d9320266`, merging `main` at `464da471` into the
branch at `41aaeff9`), with `git status` reporting exactly one conflicted
path, `tests/test_review_gateway.py`. Before resolving, verified the
diversity-selection logic the branch-only tests nominally exercised is
separately and currently covered elsewhere:
`tests/test_discovery_bootstrap_selection.py::test_bootstrap_selector_prefers_model_group_diversity`
and `::test_bootstrap_selector_spans_multiple_providers_before_repeating_one`,
plus `tests/test_model_discovery_boundaries.py`'s provider-name assertions on
`select_bootstrap_discovered_agents`, all still exist and pass at current
head and exercise the same selector the dropped
`test_build_review_orchestrator_uses_model_group_diversity` only wrapped in
an HTTP-gateway fixture around. With that confirmed, resolved the conflict by
taking `main`'s version of the file (its evidence-only-admission test suite,
no `max_agents` anywhere) rather than reintroducing a parameter `main` had
deliberately removed -- dropping the two `#971`-branch-only tests that had
gone stale against `main`'s evolved API instead of trying to keep both APIs
alive. Verified with the targeted suite (`tests/test_review_gateway.py`,
`tests/test_discovery_bootstrap_selection.py`,
`tests/test_model_discovery_boundaries.py`,
`tests/test_endpoint_race_callback_settlement.py`,
`tests/test_daemon_worker_pool_shutdown.py`: 53 passed, 0 failed), then
pushed. GitHub's `mergeable_state` for #971 now reads `blocked` (checks-only;
re-confirmed live at time of writing, head `558c8470`), not `dirty`.

### Remaining `ThreadPoolExecutor`-atexit-join instances of the same root cause

The `ThreadPoolExecutor`-registers-an-atexit-join gotcha already fixed twice
in the entries below (OpenRouter free-endpoint fetch; shared discovery
metadata fetches) recurred in two more call sites found by further Devin
Review passes on this same branch, both fixed with the identical
daemon-thread/bare-`Future` pattern:

- **`endpoint_race.race_first_valid`** (`endpoint_race.py`, commit
  `9b28bd22`) fanned its equivalent-endpoint race attempts out across a
  `ThreadPoolExecutor`. Combined with this org's default no-deadline
  `ModelClient.timeout=None`, a losing race participant stuck in an
  uncancellable provider call that never returns could hang process shutdown
  forever, even though the winner had already answered the caller and
  `race_first_valid` had already returned. Fixed by driving each attempt from
  a raw `threading.Thread(daemon=True)` built on a bare
  `concurrent.futures.Future` (the documented low-level primitive
  `ThreadPoolExecutor` itself is built on): `set_running_or_notify_cancel()`
  preserves the existing "cancelled before it started never calls the
  provider" duplicate-cost guarantee, and `wait()`/`future.cancel()`/
  `future.result()`/`future.exception()` behave identically to the prior
  executor-backed futures. All 22 pre-existing tests in
  `tests/test_endpoint_race.py` and
  `tests/test_endpoint_race_terminal_provenance.py` pass unmodified. New
  regression
  `tests/test_endpoint_race_process_exit.py::test_uncancellable_loser_never_returning_does_not_block_process_exit`
  (a subprocess test: one attempt blocks on an `Event` nothing ever sets, the
  fast attempt wins, script falls through to a normal unforced exit) hung the
  full 15s bound and was killed (RED) against the pre-fix code, and exits in
  well under 5s (GREEN) with the fix. Full suite at that commit: 3430 passed,
  6 failed (same named pre-existing sandbox gaps as the entries below), 2
  skipped.
- **`ProviderEmbeddingBatchBackend`** (`batch_routing.py`, commit `59b2fc87`)
  drove its durable, pollable job queue through a `ThreadPoolExecutor` at
  every construction site (crash recovery in `__init__`, and `start()`);
  `cost_router.py`'s `_provider_embedding_backend()` passes
  `execution_timeout_seconds=None` by default, and even a finite value there
  is only a cooperative check made after a runner returns, never a preemptive
  cancellation of an in-flight call -- so a hung provider-embedding runner
  could block that join, and therefore process shutdown, forever, even after
  `close()` had already been called. Fixed with a new `_DaemonWorkerPool`
  primitive: a fixed-size pool of `threading.Thread(daemon=True)` workers
  pulling `(fn, args)` off a `queue.Queue`, exposing the exact
  `submit()`/`shutdown(wait=, cancel_futures=)` surface `ThreadPoolExecutor`
  has (including the surface a pre-existing test double reaches into
  directly). The pool stays fixed-size (matching `max_concurrency`), workers
  spawn lazily on `submit()`, and every durability/claim/recovery/publish
  code path (`_run_job`, `_run_claimed_job`, `_execution_deadline`,
  `_fail_expired_job`, `_publish_terminal`, reserve/start/cancel/poll/wait)
  is unchanged. New regression
  `tests/test_provider_embedding_batch_backend_process_exit.py::test_hung_provider_embedding_runner_does_not_block_process_exit_after_close`
  (subprocess test, same shape as above) is RED against the pre-fix code and
  GREEN with the fix. `tests/test_provider_embedding_batch_backend.py` (24
  tests) passes unmodified; the broader affected 18-file suite: 294 passed, 4
  pre-existing/out-of-scope failures. Full suite: 3433 passed, 6 failed, 2
  skipped -- matches the branch's known baseline exactly, no regressions.

### Regression from the `endpoint_race.py` raw-`Future` refactor: unsettled `Future` on a raising callback

`race_first_valid`'s raw-`Future` rewrite above (`9b28bd22`) called the
caller-supplied `on_attempt_complete` observer callback and then
unconditionally called `future.set_result(value)` on the success path -- but
if the callback itself raised, that exception propagated up through the
worker thread and the `Future` was left permanently `RUNNING`, so `wait()`/
`future.result()` on an unbounded (`deadline_seconds=None`) race could hang
forever, silently reintroducing the exact class of bug the `ThreadPoolExecutor`
removal had just fixed (`ThreadPoolExecutor` used to settle a `Future` with a
raised worker-callback's exception automatically; the bare-`Future` rewrite
had to reimplement that contract explicitly and initially missed the
success-path case). Fixed in commit `a3afc800`: both the failure-path and
success-path callback invocations are now wrapped in `try`/`except
BaseException`, and any callback exception settles the `Future` via
`future.set_exception(...)` on whichever path it occurred, so an observer
failure can never strand a `Future` mid-race. Regression coverage added in
`tests/test_endpoint_race_callback_settlement.py` (commit `83582ad7`)
exercises callback failures after both a successful and a failed provider
attempt, with `deadline_seconds=None`. Traced/documented in
`CHANGELOG.d/endpoint-race-callback-settlement.md` (commit `742b5d52`).

### Hardening: `_DaemonWorkerPool.submit()` now fails closed after `shutdown()`

A further Devin Review pass on the new `_DaemonWorkerPool` (added above in
`59b2fc87`) found an Info-severity gap: `shutdown()` set no closed flag, so a
concurrent direct `submit()` could enqueue real work behind the shutdown
sentinels every worker exits on -- work no worker would ever pick up again.
Stock `ThreadPoolExecutor.submit()` raises `RuntimeError` once `shutdown()`
has run; `_DaemonWorkerPool` did not replicate that fail-fast contract.
Traced every current call site: `ProviderEmbeddingBatchBackend` only calls
`submit()` from `__init__` (before any external reference to `self` exists)
and from `start()`, and both `start()` and `close()` already serialize
through the backend's own `_executor_lock` with `start()` checking
`self._closed` first -- so today's actual production risk was narrow -- but
a standalone primitive should not depend on every future caller reproducing
that locking discipline. Fixed in commit `18a76eb5`: a `self._shutdown` flag,
set under the pool's existing `_workers_lock` inside `shutdown()` and checked
under the same lock at the top of `submit()` (which now also enqueues under
that lock, not before acquiring it), so the check and the
enqueue/shutdown transition can never interleave; `submit()` now raises
`RuntimeError("cannot schedule new work after shutdown")` instead of
silently queuing behind the sentinels. New regression
`tests/test_provider_embedding_batch_backend.py::test_daemon_worker_pool_submit_after_shutdown_raises_instead_of_stranding_work`
and a follow-on standalone regression `tests/test_daemon_worker_pool_shutdown.py`
(commit `02389e2f`) both pass; the broader 14-file affected suite: 210
passed, the same 4 pre-existing tokenizer-unavailable ZDR failures.
Traced/documented in `CHANGELOG.d/provider-embedding-daemon-worker-pool.md`
(commit `558c8470`).

### False-positive analysis preserved as evidence: a proposed `provider_routing` equality guard is non-causal

A separately, concurrently pushed self-fix workflow on this same branch
(`.github/workflows/source-fix-971-live-review-quality.yml` +
`scripts/ci/pr971_live_review_quality_repair.py`) proposed two repairs: (1)
bounding the OpenRouter free-endpoint worker fetch to eight daemon workers --
already independently correct and already landed in production (commit
`0d774450`, this file's "unbounded per-model OS thread allocation" entry
below), so this half was fully superseded before the workflow could ever run;
and (2) adding `or request.provider_routing != first.provider_routing` to
`_run_provider_embeddings`'s (`cost_router.py`) existing
`model`/`agent_id`/`zdr_only` homogeneity guard, on the theory that equal
`model`/`agent_id`/`zdr_only` fields could still coalesce two requests
carrying different persisted `provider_routing` metadata into one batch.

Traced before applying anything: `EmbeddingBatchRequest.provider_routing`
(`batch_routing.py`) is read in exactly one place in the whole codebase,
`EmbeddingBatchRequest.to_jsonl_line()`, which serializes it into the OpenAI
Batch API JSONL request body (`body["provider"] = dict(self.provider_routing)`)
for the separate JSONL-batch-submission path. `_run_provider_embeddings`
never calls `to_jsonl_line()` and never reads `provider_routing` anywhere in
its body -- confirmed by reading the function in full: its homogeneity check
and its downstream `_run_embedding_shard`/client calls only ever reference
`model`, `agent_id`, and `zdr_only`. The proposed guard was therefore
non-causal for the execution path it targeted: no request routed through
`_run_provider_embeddings` can have its provider behavior affected by
`provider_routing` at all, matching or mismatching. **Not applied** -- kept
as verified false-positive evidence rather than blindly implementing an
external suggestion. The stale workflow and its helper script were removed
directly (commits `0247eca9`, `d388564c`) per this branch's standing "no
purpose-complete self-modifying/source-fix workflows" rule, since the
worker-bound half could never re-apply against the new head (its
`replace_once` target text no longer exists there) and the `provider_routing`
half was confirmed to fix nothing real.

### Verification

Directly re-run in this session against current head `558c8470`:
`tests/test_review_gateway.py`, `tests/test_discovery_bootstrap_selection.py`,
`tests/test_model_discovery_boundaries.py`,
`tests/test_endpoint_race_callback_settlement.py`, and
`tests/test_daemon_worker_pool_shutdown.py` together -- 53 passed, 0 failed.
Each individual fix above additionally carries its own RED-before/GREEN-after
subprocess or in-process regression and its own contemporaneous full-suite
run (3430-3433 passed, 6 failed -- the same named pre-existing/out-of-scope
sandbox gaps throughout this file's 2026-09-02 entries: tokenizer-unavailable
`test_batch_embeddings.py` ZDR tests, the unavailable `fast_mlsirm` module,
and one `usage_source` spend-analytics assertion -- 2 skipped), recorded in
each commit message and reproduced here rather than re-typed from memory.
`git fetch origin fix/model-group-timeout-openrouter` immediately before
writing this entry showed head unchanged at `558c8470`; the PR's live
`mergeable_state` was `blocked` at the same check.

### Remaining open work carried forward

1. **Bootstrap admission's hand-authored diversity/tie-break heuristics**
   (`model_discovery.py`'s `select_bootstrap_discovered_agents`:
   representative request weights, lexical tie-breakers,
   provider/model-group pass ordering, incomplete/equal-evidence fallbacks)
   still need a research-/evidence-backed decision model, or a documented
   fail-closed replacement when evidence cannot uniquely justify a decision
   -- not a repair by changing constants, weights, quotas, or tie-break
   strings.
2. **The hourly OpenCode workflow's `cancel-in-progress: false` concurrency
   gap**: a single wedged run can occupy the `opencode-hourly-loop`
   concurrency group for up to GitHub's implicit ~360-minute hosted-runner
   ceiling, serializing every later hourly trigger behind it rather than
   running it. This needs a durable/resumable contextual-orchestrator-owned
   execution/checkpoint/re-dispatch boundary preserving exact-head identity
   across external runner termination -- not a leaf-authored elapsed-time
   cutoff, which would violate this org's `timeout=null` model-inference
   policy. A related but narrower fix has already been opened separately as
   PR #1027 ("fix(ci): remove elapsed-time job cap on the hourly loop; pin
   model to orchestrator/free", head `ad9c23c2`, open/draft as of this
   entry): it removes the `loop` job's `timeout-minutes` cap entirely and
   pins `orchestrator/auto` -> `orchestrator/free`, but its own description
   explicitly does not attempt the checkpointing/resumability piece, which
   remains open.
3. **Legacy bootstrap identifier-generation mixing**: bootstrap reporting can
   expose a fingerprinted `selected_agent_ids` identity while
   `enabled_agent_ids` retains the migrated legacy persisted identity for the
   same endpoint. Consumer semantics need one identity-consistent contract,
   or explicitly typed generated-vs-persisted identifiers.

These are large-scope architectural items, deliberately left untouched by
today's session rather than patched narrowly.

## 2026-09-02 PR #971: unbounded per-model OS thread allocation in OpenRouter free-endpoint discovery

Observation time: 2026-09-02 Asia/Seoul. Follow-up correction to the
"unbounded provider discovery and single-provider bootstrap concentration"
fix recorded below: that fix's own `_openrouter_free_model_endpoints`
rewrite (raw `threading.Thread(daemon=True)` workers instead of a
`ThreadPoolExecutor`, to avoid blocking interpreter shutdown) left a
separate, distinct gap, independently reported by a Devin Review comment on
PR #971 and independently re-verified against current-head code before any
change was made.

### Finding (Devin Review, PR #971, `contextual_orchestrator/model_discovery.py`)

> Free-model discovery creates unbounded threads
>
> When OpenRouter lists many free models, `workers` allocates one thread per
> row. Large catalogs can exhaust memory or prevent provider discovery from
> starting.

### Root cause

`_openrouter_free_model_endpoints` built one `threading.Thread` object per
free model up front (`workers = [threading.Thread(...) for model_id in
model_ids]`) and started every one of them immediately. A
`threading.Semaphore(min(8, len(model_ids) or 1))` bounded how many of those
threads could do real fetch *work* concurrently, but did nothing to bound
how many native OS threads were *created and started* in the first place --
each with real kernel/stack allocation overhead. A catalog of hundreds or
thousands of free models (OpenRouter's actual free-tier catalog size is not
contractually bounded) would therefore still allocate and start that many
threads at once, before the semaphore ever limited anything, risking memory
exhaustion or stalling discovery before a single fetch could begin -- exactly
the finding.

### Fix

Replaced the one-thread-per-model construction with a fixed pool of at most
8 daemon worker threads that each pull model IDs from a `queue.Queue` until
it is empty, so the live thread count for this fetch stays bounded (`<= 8`)
regardless of catalog size. The already-established daemon-only,
abandon-on-hang behavior (no `ThreadPoolExecutor`, no interpreter-shutdown
block) is unchanged; each worker still simply stops draining the queue if
its current fetch hangs, while the other workers keep making independent
progress.

### Verification

New regression `test_openrouter_free_model_endpoints_caps_concurrent_thread_creation`
in `tests/test_model_discovery.py`: submits 40 free models with a
fetch that blocks on a shared `threading.Event`, samples
`threading.enumerate()` for live `openrouter-endpoints`-named threads while
every fetch that will ever start is blocked, and asserts the count is `<= 8`
(not 40). RED confirmed against the pre-fix one-thread-per-model
implementation (40 live threads observed for 40 models); GREEN after the
fixed-pool fix (`<= 8`). The pre-existing hang-safety regression
(`test_openrouter_free_model_endpoints_hang_does_not_block_process_exit`)
continues to pass unchanged. Full suite: 3384 passed, 7 failed (all
pre-existing/out-of-scope: 4x missing native `_token_packer` extension in
`test_batch_embeddings.py`, the still-in-progress terminal-embedding-failover
finding tracked separately, missing `fast_mlsirm` module, and the
tokenizer-mismatch `test_spend_analytics.py` sandbox artifact), 2 skipped.
`interrogate -f 100 contextual_orchestrator/model_discovery.py`: 100%.

## 2026-09-02 PR #971: terminal-failure batch embedding documents restored endpoint health

Observation time: 2026-09-02 Asia/Seoul. Closes the remaining still-open
review blocker carried in PR #971's own description ("terminal
failed/cancelled/rejected batch documents must not clear endpoint circuit
failures, and incomplete synchronous documents must be recorded through the
shared embedding-failure path before failover"): the synchronous-document
half of that sentence was already fixed (see the "synchronous `/v1/embeddings`
member result ... bypassed `orchestrator._record_embedding_failure`" entry in
`CHANGELOG.md`'s `## [0.2.0] - Unreleased`); this entry is the terminal-batch
half. Independently re-verified against current-head code before any change
was made (never trusted as stated) -- confirmed genuinely still broken, not
already fixed or stale.

### Finding (Devin Review, PR #971, `contextual_orchestrator/server.py`)

> Failed embedding jobs restore endpoint health
>
> When a batch returns a terminal failure, `observe_success` records success
> and clears its circuit. Later requests keep selecting the failed endpoint.

### Root cause

The `/v1/batch/embeddings` HTTP handler's member-failover loop (the `for
embedding_agent in embedding_agents:` loop calling
`coordinator.complete_embeddings_batch(...)`) recorded success
unconditionally on any call that returned without raising:

```python
except Exception as exc:
    last_embedding_error = exc
    orchestrator._record_embedding_failure(embedding_agent, "/v1/batch/embeddings", exc)
    continue
orchestrator._group_router.observe_success(embedding_agent.id, ...)
orchestrator._record_success(embedding_agent.id)
break
...
is_complete = document.get("status") == "completed"  # only decides the HTTP status code
```

`complete_embeddings_batch` submits the batch and returns whatever document
`CostRoutingCoordinator.embeddings_batch_document` produces for it -- which
can be a **terminal-failure document** (`status` of `"failed"`,
`"cancelled"`, or `"rejected"` -- the exact set
`embeddings_batch_document` itself checks to stop emitting a polling
cadence) returned *normally*, with no exception raised. The bug was
ordering, not a missing check: `observe_success`/`_record_success` ran and
the loop `break`-ed *before* the terminal-status check the same function
already computed one line later (`is_complete`) -- that check only ever
gated the HTTP response code (200 vs 202), never success recording or
failover. So a genuinely failed batch member still marked its endpoint
healthy and cleared its circuit breaker; later requests kept selecting that
broken endpoint instead of failing over to a healthy one. The sibling
synchronous `/v1/embeddings` handler in the same file does not have this
bug: it already gates success recording on
`document.get("status") == "completed" and document.get("embeddings") is
not None` and routes anything else through `_record_embedding_failure`
before continuing -- confirmed the only other `observe_success`/
`_record_success` call site in `server.py`, so this was the one remaining
instance of the pattern in this file.

### Fix

`contextual_orchestrator/server.py`, `/v1/batch/embeddings` handler:

- Added a module-level `_TERMINAL_EMBEDDING_BATCH_FAILURE_STATUSES =
  frozenset({"failed", "cancelled", "rejected"})`, matching
  `CostRoutingCoordinator.embeddings_batch_document`'s own terminal-status
  vocabulary (`cost_router.py`).
- The loop now checks `document.get("status")` against that set
  immediately after a successful (non-raising) call and before recording
  any success: a terminal-failure document builds a synthetic
  `RuntimeError(f"embedding batch member ended with {document.get('status')}")`,
  routes it through the same shared `orchestrator._record_embedding_failure`
  recorder an exception would use, discards the document, and `continue`s
  to the next candidate agent -- the same failover shape a raised exception
  already got. Only a document whose status is *not* a terminal failure
  (`"completed"`, or an in-flight status such as `"queued"`, `"validating"`,
  `"running"`) still records success and `break`s.
- No other file changed; `model_discovery.py` and the rest of
  `cost_router.py` are out of scope for this fix (separate in-flight work on
  this branch).

### Verification

RED-before/GREEN-after. A pre-existing test in
`tests/test_pr971_review_quality_regressions.py` --
`test_terminal_embedding_batch_document_fails_over_before_marking_health`
(mocks `coordinator.complete_embeddings_batch` to return a `status: "failed"`
document for the first, higher-priority agent and a non-terminal
`status: "validating"` document for the second, then posts to
`/v1/batch/embeddings`) -- failed pre-fix (asserted `attempted == [first.id,
second.id]`; pre-fix code `break`-ed after the first agent's false success,
so only `[first.id]` was ever attempted and the response carried the failed
`batch_id`) and passes post-fix (both agents attempted, 202 response carries
the second agent's `"accepted-batch"` id). Directly confirmed with an
additional ad hoc spy harness (not committed) around
`orchestrator._group_router.observe_success`, `orchestrator._record_success`,
and `orchestrator._record_embedding_failure` for the same scenario:
post-fix, `observe_success`/`_record_success` are called only with the
second (healthy) agent's id, and `_record_embedding_failure` is called
exactly once with the first (failed) agent's id and a `RuntimeError`
("embedding batch member ended with failed") -- i.e. the failed endpoint's
circuit is never falsely cleared, and it is routed through the same
recorder an exception would use. Full suite and `interrogate --fail-under
100` confirmed green apart from named pre-existing sandbox-only failures
unrelated to this change.

## 2026-09-02 PR #971: recovered ZDR embedding batch bypassed request-policy enforcement

Observation time: 2026-09-02 Asia/Seoul. Follow-up correction to the
"recovered ZDR batch not re-validated" fix recorded in the
"embedding recovery/deadline and legacy-id quarantine review" entry below:
that fix's own re-validation left a gap, independently reported by a Devin
Review security-level comment on PR #971 and independently re-verified
against current-head code before any change was made (never trusted as
stated).

### Finding (Devin Review, PR #971, `contextual_orchestrator/cost_router.py`)

> Recovered embeddings bypass ZDR enforcement
>
> Recovered `zdr_only` jobs never restore `request_policy`, so OpenRouter
> omits `provider.zdr`. Mixed privacy identities can also execute under the
> first request's policy.

### Root cause

`_run_provider_embeddings` is the replay entry point
`ProviderEmbeddingBatchBackend` calls when a durably-queued embedding job is
recovered after a process restart and executed on a background worker
thread. The earlier fix (see "embedding recovery/deadline and legacy-id
quarantine review" below) added a check that the resolved agent still
carries the `privacy:zdr` tag, but that check is necessary and not
sufficient:

1. **The `request_policy` contextvar was never restored.** OpenRouter's
   enforcing `provider.zdr: true` request field is applied by
   `_pin_openrouter_zdr` (`orchestrator.py`), which branches on the
   `_REQUEST_ZDR_ONLY` contextvar set by `TaskOrchestrator.request_policy(...)`
   -- not on the request's own `zdr_only` field. The submission-time
   `request_policy(zdr_only)` scope used by every synchronous call site
   (`cost_router.py` lines ~636, ~770, ~1038, ~1417) is a `ContextVar`,
   which does not cross the thread boundary `ProviderEmbeddingBatchBackend`
   replays a recovered job across. `_run_provider_embeddings` called
   `self._run_embedding_shard(agent, shard)` -> `self.orchestrator.client.embed`
   /`embed_with_usage` -> `_send_raw` -> `_pin_openrouter_zdr` with no
   `request_policy` scope active on that thread at all, so the pin's branch
   condition was always false for a recovered batch regardless of
   `first.zdr_only` -- the actual HTTP request to OpenRouter silently
   omitted `provider.zdr`, even though the tag check already re-validated
   the agent and the code's own comment believed privacy safety was
   handled.
2. **No per-request `zdr_only` homogeneity check.** The batch's existing
   consistency check only asserted every request shared `model` and
   `agent_id`:
   `EmbeddingBatchRequest` carries `zdr_only` per request (`batch_routing.py`),
   but nothing compared it across the batch. A batch mixing
   `zdr_only=True` and `zdr_only=False` requests under the same
   `agent_id` executed entirely under `first`'s policy -- either
   over-restricting a non-ZDR request or, the real risk, silently
   under-restricting a ZDR request that was not first in the list.

### Fix

`_run_provider_embeddings` (`contextual_orchestrator/cost_router.py`):

- Wraps the sharded `_run_embedding_shard` execution loop in
  `with self.orchestrator.request_policy(first.zdr_only): ...` -- the same
  context-manager pattern already used at every other client call site in
  this file -- so the OpenRouter ZDR pin is correctly re-armed for a
  recovered batch's actual client call(s), not just checked-and-trusted at
  the tag level.
- Extends the existing route-homogeneity check to also require every
  request in the batch share `first.zdr_only`, alongside the pre-existing
  `model`/`agent_id` check, raising the same `RuntimeError` (fail closed,
  same style as the adjacent tag-mismatch check) when they diverge, instead
  of silently running the whole batch under `first`'s policy.

Both changes are additive and scoped to `_run_provider_embeddings`; no
other call site or the batch-submission path changed.

### Why this is fail-closed and ZDR-first

This repo's stated policy is ZDR-first: every LLM path routes through the
`orchestrator/free` pool and privacy-scoped requests must be provably
zero-retention, not merely assumed so. Before this fix, a *recovered*
`zdr_only` request could silently execute without the provider-side
enforcement its caller explicitly requested -- a privacy guarantee that
looked re-validated (the tag check ran and passed) while the request that
actually left the process carried no enforcement of it. Both parts of the
fix restore the same fail-closed shape used everywhere else in this file:
mismatched privacy identity now raises before any request is sent, and a
matching identity now genuinely carries its enforcement through to the
provider, rather than being asserted once and then dropped on the
replay path.

### Verification

RED-before/GREEN-after, both already present in
`tests/test_pr971_review_quality_regressions.py` (added ahead of this fix
landing) and confirmed to fail against pre-fix code, pass against the fix:

- `test_recovered_zdr_batch_reenters_request_privacy_scope` -- monkeypatches
  `orchestrator.request_policy` to record every `zdr_only` value it is
  entered with, runs a recovered single-request ZDR batch through
  `_run_provider_embeddings`, and asserts `request_policy` was entered with
  `True` exactly once. Failed pre-fix (`entries == []`, the scope was never
  entered); passes post-fix.
- `test_provider_embedding_batch_rejects_mixed_privacy_identity` -- builds
  a two-request batch sharing `model`/`agent_id` but differing
  `zdr_only`, and asserts `_run_provider_embeddings` raises `RuntimeError`
  matching `"privacy policy"`. Pre-fix, the batch executed without raising;
  post-fix it fails closed.

## 2026-09-02 PR #971: unbounded provider discovery and single-provider bootstrap concentration

Observation time: 2026-09-02 Asia/Seoul. This closes the two remaining
unaddressed items from PR #971's review-blocker list, both independently
verified against current-head code rather than trusted as stated.

### Summary

- **Model discovery had no separately bounded/cancellable per-provider
  deadline.** `discover_all_models` (`contextual_orchestrator/model_discovery.py`)
  ran a plain sequential `for source in sources: discover_provider_models(...)`
  loop with no thread, no `asyncio.wait_for`, and no join timeout around any
  individual provider's call -- confirmed genuinely unbounded, not merely
  a stale claim. `DISCOVERY_TIMEOUT_SECONDS` (the per-HTTP-call socket
  timeout passed *into* each fetch) defaults to `None` per #971's own
  no-inference-deadline design boundary, and even set to a finite value it
  only bounds one socket read at a time inside a provider's multi-fetch
  discovery attempt -- it cannot bound a hang that ignores that parameter
  entirely (confirmed with a mock discovery call blocking on an `Event`
  nothing ever sets). A stalled provider therefore blocked discovery of
  every later, healthy provider forever. Fixed: `discover_all_models` now
  runs each provider's discovery on its own daemon thread and stops
  waiting once a new, separately configured
  `PROVIDER_DISCOVERY_DEADLINE_SECONDS` (default 30.0s) elapses, recording
  a `ProviderDiscoveryError(error_code="discovery_timeout")` for that
  provider and continuing to the next one; the abandoned thread is
  daemonized so it cannot block interpreter shutdown, and its eventual
  result (if any) is discarded. This constant is independent of both
  `DISCOVERY_TIMEOUT_SECONDS` and `ModelClient.timeout` -- it is never
  reused or repurposed from either -- and an explicit
  `discovery_deadline=None` still opts back into the pre-fix unbounded
  wait. RED-before/GREEN-after:
  `tests/test_model_discovery.py::test_discover_all_models_bounds_a_stalled_provider_so_later_providers_still_complete`
  (mocked `discover_provider_models` hangs forever for one source; asserted
  the second source's model still arrives and the whole call returns in
  well under 5s) hung the test process indefinitely against the pre-fix
  sequential loop (had to be killed by an outer `timeout`) and passes in
  under 2s with the fix.
- **Bootstrap diversity was model-group-diverse only, not genuinely
  provider-diverse, despite claiming otherwise.** This repo's own
  `CLAUDE.md` and `tests/test_discovery_bootstrap_selection.py`'s title/
  assertions ("missing provider-diverse bootstrap selector") both describe
  `select_bootstrap_discovered_agents` as layering provider-diverse
  selection on top of cheapest-price ranking. The actual first pass
  (`model_discovery.py`) admitted at most one endpoint per **model group**
  (the provider-declared exact model identity) and never checked
  `provider_name` at all, so several cheap, distinctly-named models from
  one provider could -- and, in the existing
  `test_bootstrap_selector_prefers_model_group_diversity` fixture, did --
  fill most or all of a bootstrap pool before a genuinely independent,
  viable alternative provider was ever tried: an apparently diverse pool
  (distinct model names) that was actually concentrated on one provider's
  continued availability. `contextual_orchestrator/provider_bootstrap.py`'s
  separate `select_model_group_diverse_models` was deliberately left
  unchanged: it never claims provider diversity (its own name and
  docstring say "model group" only), and its own test suite has an
  explicit, deliberate price-honesty-over-diversity contract (an
  unknown-priced model must never outrank a same-provider model with a
  known price) that a blanket provider constraint would have broken --
  exactly the "unless evidence/contract explicitly chooses otherwise" case
  the review finding itself carved out. Fixed (`select_bootstrap_discovered_agents`
  only): a new first pass now admits at most one endpoint per provider
  *and* per model group; once every viable provider has contributed once
  (or capacity runs out), a second pass fills remaining slots from
  still-untried model groups regardless of provider; a final pass, as
  before, falls back to duplicate model-group endpoints only once real
  diversity is exhausted. Two downstream tests that had pinned the old,
  single-provider-concentrated outcome as correct
  (`tests/test_discovery_bootstrap_selection.py::test_bootstrap_selector_prefers_model_group_diversity`,
  `tests/test_review_gateway.py::test_build_review_orchestrator_uses_model_group_diversity`)
  were updated to the corrected, genuinely cross-provider expectation.
  RED-before/GREEN-after: the new
  `test_bootstrap_selector_spans_multiple_providers_before_repeating_one`
  (three individually-cheaper same-provider models plus one pricier
  independent-provider model, pool size 2) failed against the pre-fix
  algorithm with the pool collapsed onto the single cheaper provider
  (`{'openrouter'} == {'openai', 'openrouter'}`) and passes with the fix.
  **2026-09-08 no-heuristics correction (Proposed):** provider identity and
  exact model-group identity are observations, not an outage probability,
  expected utility, or psychometric quality model. The three-pass proposal
  could therefore displace a lower-cost candidate or reorder a complete pool
  solely because another candidate had a distinct label. Both bootstrap
  selectors now compare every diversity proposal with the price-evidenced
  candidate sequence and fail closed when they differ. Equal or incomplete
  evidence remains fail-closed as before. New RED-before/GREEN-after fixtures
  cover bounded model-group/provider displacement and complete-pool
  reordering; the two earlier fixtures that required an unmodeled,
  more-expensive provider were corrected to require rejection.
  Raw candidates remain available for a future released allocation contract;
  this branch does not invent outage weights, provider quotas, or a fallback
  tie-break.
- While landing the above, a concurrently-pushed, staged (not-yet-applied)
  self-modifying repair workflow was discovered on the same branch --
  `.github/workflows/source-fix-971-review-quality.yml` and
  `scripts/ci/source_fix_971_review_quality.py`, added by a parallel
  session targeting these same two findings. Its proposed fix was weaker
  and, for the second finding, targeted the wrong function: it would have
  (a) simply set the pre-existing `DISCOVERY_TIMEOUT_SECONDS` to a fixed
  15.0s per-HTTP-call socket timeout -- not a separately bounded/
  cancellable per-provider mechanism, so it would not have caught a hang
  that ignores that parameter (verified: this branch's own new
  `test_discover_all_models_bounds_a_stalled_provider_so_later_providers_still_complete`
  mocks exactly that and would still fail against a mere socket-timeout
  fix); and (b) added provider-diversity logic to
  `provider_bootstrap.py`'s `select_model_group_diverse_models` -- the
  function this repo's own tests deliberately keep price-honesty-over-
  diversity for -- without updating its existing
  `test_diverse_selection_prefers_known_cost_without_treating_unknown_as_free`
  contract, which its own proposed algorithm would have broken. Since its
  own "revalidate exact unchanged writer head" step (queued run
  `33618086791` on `170103c0`) fails closed the moment the branch head
  moves, the ordinary commits above were pushed immediately to win that
  race safely, and the now-fully-superseded temp workflow/script were
  then deleted per the branch's standing "no purpose-complete self-
  modifying/source-fix workflows" rule (it could never successfully run
  again against the new head regardless) -- restoring `interrogate` to
  100% (the deleted script's undocumented `main()` had briefly dropped it
  to 99.9% after the merge that brought the staged files in).

## 2026-09-02 PR #971: shared discovery metadata fetches bypassed the discovery deadline

Observation time: 2026-09-02 Asia/Seoul. Closes a Devin Review finding
(bug id `BUG_pr-review-job-93783e6ce7a2440ab487ebce4076fe6f_0002`,
`contextual_orchestrator/model_discovery.py` line 52) raised against this same
branch after the per-provider `PROVIDER_DISCOVERY_DEADLINE_SECONDS` bound
above landed, independently verified against current-head code rather than
trusted as stated. A related CodeRabbit finding on the same file, surfaced
while this fix was in progress, is folded into the same entry below.

### Finding and root cause

`discover_all_models`'s per-provider `discovery_deadline` bound
(`_discover_provider_models_bounded`, documented in the section above) covers
only `discover_provider_models` inside the per-provider loop. Three *shared*
metadata fetches the same function makes outside that loop were confirmed
still wholly unbounded, each receiving only `timeout` (the per-HTTP-call
socket timeout, `None`/unbounded by #971's own design default):

- `_fetch_models_dev_metadata(timeout=timeout)` -- called once, *before* the
  per-provider loop starts, whenever any registered source declares
  `models_dev_provider_id` (`opencode_zen`, `nvidia_nim`, `nvidia_nim_sub`,
  `openai`).
- `_openrouter_zdr_model_ids(timeout=timeout)` -- called unconditionally
  *after* the per-provider loop finishes.
- `openrouter_paid_inference_available(timeout=timeout)` -- called *after*
  the loop, only once an `OPENROUTER_API_KEY` credential is registered.

None of these three ran on the bounded daemon thread the per-provider loop
already used; a connection accepted but never answered (or any other hang
the per-request socket timeout cannot catch -- the same class of bug the
per-provider fix above already addressed) on any one of them could block
`discover_all_models`, and therefore first-boot pool bootstrapping,
indefinitely regardless of `discovery_deadline`.

### Fix

Reuses the exact mechanism already reviewed favorably for the per-provider
bound rather than inventing a second one: `_discover_provider_models_bounded`
is generalized into a shared primitive, `_run_bounded_by_deadline` (runs the
wrapped call on its own daemon thread, `worker.join(timeout=discovery_deadline)`,
abandons a still-alive worker past the deadline -- Python threads cannot be
forcibly killed, so "cancellable" means "the caller stops waiting"). All four
call sites -- the per-provider attempt plus the three shared fetches -- now
go through this one helper under the same `discovery_deadline` parameter
`discover_all_models` already accepted and threaded through; an explicit
`discovery_deadline=None` still opts every one of them back into the pre-fix
unbounded wait.

### Fail-closed reasoning for each timeout fallback

The per-provider path keeps its existing behavior (raises
`ProviderDiscoveryError(error_code="discovery_timeout")`, recorded in the
caller's `errors` list). Each shared fetch has no such per-provider error
list to append to; on timeout, `_run_bounded_by_deadline`'s `on_timeout`
callback returns the *exact same fallback value the wrapped function already
returns for an ordinary fetch failure* -- never a new, more permissive value
-- so the fail-closed posture already established for a network error is
identical for a network hang. Traced downstream for each:

- `_fetch_models_dev_metadata` ordinary-failure return is `None`.
  `_merge_models_dev_metadata` (`model_discovery.py`) treats non-dict
  metadata as "no evidence" and returns the provider's own catalog payload
  unenriched (no cost/modality enrichment, not "verified free" or "verified
  priced") -- confirmed by reading the function: `provider_row =
  metadata.get(provider) if isinstance(metadata, dict) else None`, then
  `if not isinstance(rows, list) or not isinstance(models, dict): return
  payload`. On timeout, the bounded wrapper returns `None` -- not the
  `_NOT_FETCHED` sentinel -- so `discover_provider_models` treats the
  metadata as "already fetched, unavailable" and does not re-attempt the
  same stalled fetch a second time inside the (separately bounded)
  per-provider thread; the provider's own catalog listing still completes.
- `_openrouter_zdr_model_ids` ordinary-failure return is an empty `set()`.
  `_apply_discovered_model_evidence` short-circuits on an empty set
  (`if not zdr_model_ids: return discovered`) and leaves every row's
  `zdr_capable` exactly as `discover_provider_models` already set it --
  never *adds* ZDR-capable status on missing/timed-out evidence, only ever
  on a positive, exact model-id match. On timeout, the bounded wrapper
  returns `set()`.
- `openrouter_paid_inference_available` ordinary-failure/"could not
  determine" return is `None`. `apply_openrouter_spend_admission`'s existing
  rule is `spend_admitted = provider != "openrouter" or is_free or
  paid_available is True` -- a paid (non-free) OpenRouter row is
  `spend_admitted=False` for anything other than `paid_available is True`,
  so `None` (timeout) and `False` (attested no credit) are both already
  fail-closed today; the timeout fallback changes nothing about that
  contract. On timeout, the bounded wrapper returns `None`.

### Verification

RED-before/GREEN-after, one regression test per shared fetch plus the
existing per-provider one, all mocking the target function itself (not the
transport layer) to block on a `threading.Event` nothing ever sets, mirroring
`test_discover_all_models_bounds_a_stalled_provider_so_later_providers_still_complete`'s
style:
`tests/test_model_discovery.py::test_discover_all_models_bounds_a_stalled_models_dev_metadata_fetch`,
`::test_discover_all_models_bounds_a_stalled_openrouter_zdr_fetch`,
`::test_discover_all_models_bounds_a_stalled_openrouter_paid_inference_fetch`.
Each hung the test process indefinitely against the pre-fix code (verified by
temporarily reverting the fix and killing the hung run with an outer
`timeout` -- exit 143 on all three) and passes in well under 5s with the fix.
`tests/test_model_discovery.py`, `tests/test_discovery_bootstrap_selection.py`,
`tests/test_review_gateway.py`, and every other test file importing
`model_discovery` (`test_auto_discovery_server.py`,
`test_chat_model_capability_isolation.py`, `test_ci_gateway_bootstrap.py`,
`test_discover_models_cli.py`, `test_model_discovery_boundaries.py`,
`test_openrouter_free_canary.py`, `test_privacy_policy_analysis.py`,
`test_provider_bootstrap*.py`, `test_provider_catalog_*.py`) pass unchanged.
`interrogate` remains 100%.

### Related CodeRabbit finding: a hung endpoint fetch could block process exit

`_openrouter_free_model_endpoints` (called from `discover_provider_models`'s
OpenRouter branch, itself already inside the per-provider bounded thread
above) fanned its per-model endpoint fetch out across a
`concurrent.futures.ThreadPoolExecutor`. Verified with a local repro before
changing anything: even wrapping the whole call in an already-`daemon=True`
outer thread does not stop a still-hung `ThreadPoolExecutor` worker from
blocking process shutdown -- `concurrent.futures.thread` registers its own
interpreter-exit hook that unconditionally joins every still-running worker
it created, independent of the daemon status of whichever thread constructed
the executor. A bare script reproducing this (one daemon thread, one
`ThreadPoolExecutor` with a permanently blocked worker, then a normal,
unforced fall-through to script exit) hung for a bounded outer `timeout`
command's full 10s and was killed (exit 124) against the pre-fix code, and
exited cleanly in well under 1s once the fetch fan-out was rewritten to use
plain `threading.Thread(daemon=True)` workers (concurrency capped at 8 via a
semaphore, matching the prior `max_workers`) instead of a `ThreadPoolExecutor`
-- daemon threads carry no such exit-blocking registration, so a hung fetch
is abandoned exactly like every other stalled discovery-time network call in
this module. This is a distinct failure mode from the discovery-deadline
finding above (it is not about `discover_all_models`'s *caller* waiting too
long -- that was already bounded by the outer per-provider thread -- it is
about the *process* being unable to exit at all while an abandoned
`ThreadPoolExecutor` worker is still running), so it is documented here
rather than folded silently into the fix above.
Verified:
`tests/test_model_discovery.py::test_openrouter_free_model_endpoints_hang_does_not_block_process_exit`
(spawns a real, separate interpreter, since an in-process thread-introspection
assertion cannot distinguish "still hanging in the background" from "would
actually block this process's shutdown" -- the whole point of the finding);
RED-before (killed by the test's own bound against the reverted,
`ThreadPoolExecutor`-based code) / GREEN-after (exits well under the bound).

### Note on a concurrently-pushed, broader automated repair

The branch owner pushed `.github/workflows/source-fix-971-live-review-quality.yml`
and `tests/test_pr971_review_quality_regressions.py` directly (not through
this session) while this fix was in progress, targeting this same finding
plus three unrelated Devin Review findings (durably recovered `zdr_only`
embedding work not re-entering request-policy scope; coalesced
provider-embedding batches able to mix privacy/routing identity; terminal
failed/cancelled provider batch documents recorded as endpoint success).
This branch's `cost_router.py` fix (commit `e3fa6d9b`, see the "recovered ZDR
embedding batch bypassed request-policy enforcement" section above) landed
independently, ahead of the workflow's own repair step, and fixed the first
two of those three (both are the same `_run_provider_embeddings` gap:
missing `request_policy` re-entry and missing per-request `zdr_only`
homogeneity) -- confirmed by re-running
`tests/test_pr971_review_quality_regressions.py` after that commit landed:
`test_recovered_zdr_batch_reenters_request_privacy_scope` and
`test_provider_embedding_batch_rejects_mixed_privacy_identity` are both now
GREEN. Only the third (terminal failed/cancelled provider batch documents
recorded as endpoint success,
`test_terminal_embedding_batch_document_fails_over_before_marking_health`)
remains unfixed as of this entry -- untouched by this fix, in `server.py`.
This workflow's own regression file was verified test-by-test against the
fix in this section:
`test_discover_all_models_bounds_every_shared_metadata_fetch` (the
discovery-deadline finding this section fixes) passes against this fix --
confirming it is genuinely superseded for that one finding -- but, as of
this entry, the workflow's repair step has *not* fully served its purpose
for the remaining `server.py` finding, so it was deliberately left in
place rather than deleted, per this branch's own precedent's "delete only
once fully superseded" rule; its `model_discovery.py` `replace_once` steps
target the pre-fix literal source text this section replaces, so if ever
dispatched against this fix's head those specific steps will now fail closed
(`SystemExit`, no partial write survives past the failing step) rather than
silently reapplying a weaker, duplicate bound -- consistent with the
workflow's own "exact writer head" / "smallest causal GREEN repair" design
intent, not a bypass of it.

## 2026-09-02 PR #971: embedding recovery/deadline and legacy-id quarantine review

Observation time: 2026-09-02 Asia/Seoul.

### Summary

Bot-reported (CodeRabbit/Devin) findings on PR #971 were independently
verified against the actual current-head code (never trusted as ground
truth) and, where confirmed real, fixed with a RED-before/GREEN-after
regression test:

- **Docstring coverage** (CodeRabbit: "48.87%, threshold 80%"): not
  reproducible against this repo's own gate. `interrogate` (pinned
  `requirements-opencode-review-ci.txt`, config in `pyproject.toml`:
  `fail-under = 100`, `exclude = ["tests"]`) reports **100.0%** for the
  entire `contextual_orchestrator` package, including every file this PR's
  diff touches. Even scored with every `ignore-*` flag off (the strictest
  reading short of including `tests/`), coverage is 81.7% -- still above an
  80% bar. CodeRabbit's own "38 files" count matches this diff's combined
  source *and* test `.py` files, which strongly indicates its check scores
  test functions too; this repo deliberately excludes `tests/` from the
  docstring gate and does not conventionally docstring pytest test
  functions, which would explain the low externally-reported number. No
  docstring changes were needed.
- **Default-timeout embeddings OverflowError, failed legacy-id gateway
  probe never disabling, recovered ZDR batch not re-validated, incomplete
  sync embedding results evading the circuit breaker, durable claim-lease
  crash + unbounded-execution-timeout substitution, and the OpenRouter
  uptime collector's unbounded background fetch**: all confirmed real
  against current-head code and fixed; see the dated `CHANGELOG.md`
  entries under PR #971 for the exact mechanism, fix, and regression test
  per item.
- The branch's self-modifying one-shot repair workflows
  (`.github/workflows/source-fix-971-exact-head-review.yml`,
  `.github/workflows/source-fix-971-runtime-context-green.yml`,
  `scripts/source_fix_971_runtime_context_green.py`) were deleted per the
  standing "no purpose-complete self-modifying/source-fix workflows" rule,
  after the source/test fixes above landed as ordinary commits.

## 2026-09-02 PR #971: no-heuristics `ModelClient` default retry correction

Observation time: 2026-09-02 Asia/Seoul.

### Summary

- A fresh audit of PR #971 (`fix/model-group-timeout-openrouter`) found that
  `ModelClient` still defaulted `max_retries` to a hand-picked `2` with no
  cited standard, paper, or the org's own research (Fugu, Conductor,
  TRINITY) establishing that number.
- RED regression commit `c1dcff6e903a7cfd7dab4584d628a5fbf57cf789`
  (`tests/test_no_heuristic_default_transport_retry.py`) asserted a default
  `ModelClient` must allocate zero automatic retries, independent of
  provider/model/reasoning identity; it failed against the `max_retries=2`
  default (`2 == 0`), confirming the RED state before the fix.
- Fix applied: `ModelClient.__init__`'s `max_retries` default is now `0`
  (`contextual_orchestrator/orchestrator.py`). `docs/adr/0001-tool-execution-fallback-policy.md`
  gained a 2026-09-02 amendment recording that RFC 9110 and NIST SP 800-204
  constrain *when* retry/circuit-breaking is safe but name no specific
  numeric allocation, so the allocation is no longer library-authored;
  explicit nonzero retry budgets remain caller-owned configuration. The RED
  regression test now passes, and the focused provider/transport regression
  suites (`tests/test_provider_gateway_resilience.py`,
  `tests/test_provider_integration.py`, `tests/test_provider_error_taxonomy.py`,
  `tests/test_no_heuristic_default_transport_retry.py`) were re-run green.
- The PR's own one-shot repair machinery
  (`.github/workflows/source-fix-971-default-retry-policy.yml` and its
  trigger/script) sat `queued` for 100+ minutes under org-wide Actions
  capacity congestion and was completed manually instead of waiting further;
  the now-superseded queued run was cancelled and the one-shot machinery
  removed from the branch per the standing self-removal convention.

## 2026-09-01 Autonomous Commercialization Loop: PR #970 Merge, Token Accounting & Cost Gateway Harmonization

Observation time: 2026-09-01 Asia/Seoul.

### Summary of Completed PR Merges
- **PR #970 (`fix/provider-embedding-current-main`) Merged into `main`**:
  - Reconciled authoritative token accounting across `cost_router.py`, `cost_ledger.py`, and `token_counting.py` in accordance with ADR 0005 and ADR 0006.
  - Rust-backed exact token counter extension integrated for declared tokenizers (`count_cl100k`, `count_o200k`, `pack_cl100k`) with closed-fail behavior (`UnavailableTokenCounter`) for unsupported/unreconstructible structures.
  - Masked unmeasured usage rows to `None` with `measurement_status = "unavailable"`, ensuring zero-token schema sentinels are never exposed as measured or free usage.
  - Successfully verified complete 3,142-test project test suite (100% passing across unit, HTTP honesty, and boundary suites).

### Prior Merged PR Queue Recap
- Merged PRs: [#938](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/938), [#936](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/936), [#935](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/935), [#934](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/934), [#937](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/937), [#946](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/946), [#952](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/952), [#955](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/955), [#956](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/956), [#957](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/957), [#958](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/958), [#959](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/959), [#960](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/960), [#961](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/961), [#962](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/962), [#963](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/963), [#964](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/964), [#965](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/965), [#966](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/966), [#967](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/967), [#968](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/968), [#970](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/970).

### Next Queue Targets
- **PR #971**: `fix(embedding-router): route plain unspecified embedding batches to cheapest member`
- **PR #972**: `fix(gateway): respect client custom_id in batch chat responses`
- **PR #973**: `feat(catalog): provider latency routing telemetry and scoring`
- **Remaining Open PRs**: [#976](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/976), [#977](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/977), [#978](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/978), [#980](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/980), [#981](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/981), [#982](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/982), [#983](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/983), [#984](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/984), [#985](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/985), [#986](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/986), [#992](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/992), [#993](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/993).

## 2026-08-31 live continuation: PR queue recheck, worktree reconciliation, issue #940 deferral, and issue #927 closure

Observation time: 2026-08-31 Asia/Seoul. GitHub authentication was
re-verified first with `gh api user`. The primary checkout remained dirty
(`uv.lock` modified, `.worktrees/` untracked), so code work continued in clean
commercial-loop worktrees only.

### Open PR queue recheck and duplicate avoidance

Open PRs were re-fetched before any code change. The highest-updated queue
segment remained the overlapping OpenRouter discovery cluster:

- [#951](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/951)
  `fix(discovery): stop blanket-excluding OpenRouter from serving on ZDR grounds`
- [#950](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/950)
  `fix(discovery): gate OpenRouter evidence_only/zdr_capable per model, not per provider`
- [#949](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/949)
  `fix(discovery): route OpenRouter by model evidence`

Reconciliation evidence:

- `gh api graphql` for PR `#951` returned **no review threads** and **no
  reviews** at the observed head.
- `git range-diff origin/main...origin/pr/949 origin/main...origin/pr/950
  origin/main...origin/pr/951` showed PR `#951`'s root fix commit
  `fa0cbc85d47c08a30926c57fcb2e272d8d3fa4c0` already exists inside the broader
  `#949`/`#950` line, while `#950` adds the stricter per-model evidence gate.
- PR `#950` already had exact-head focused/full/fuzz/security checks green
  except the external `opencode-review` gate; pushing another branch with the
  same semantic fix would have duplicated an active PR contract.

Conclusion: no additional OpenRouter code was published in this invocation.
The cluster was treated as already in flight.

### Prior `commercial-loop-*` worktree reconciliation

Existing local worktrees were inspected before selecting the next unit:

| Existing worktree | Observed state on 2026-08-31 | Decision |
|---|---|---|
| `../commercial-loop-20260831-pr936-root-cause` | current head of open PR [#938](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/938) | Preserve; active PR head |
| `../commercial-loop-20260831-pr911-removed-member` | current head of open PR [#911](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/911) | Preserve; active PR head |
| `../commercial-loop-20260830-pr911-root-cause` | diverged local branch with uncommitted edits | Preserve; not authoritative |
| `../commercial-loop-20260831-issue927-root` | committed root-cause branch with no open PR | Reuse for this invocation |

No superseded worktree was removed because no exact diff-coverage proof was
recorded for every local-only change still present.

### Highest-leverage issue selection

Issue [#940](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/940)
was reviewed next because it is the highest-updated product-gap issue and
directly affects `orchestrator/free` reliability. It was **deferred for this
hour** rather than patched opportunistically because the issue's own root-cause
record is correct: a production-safe fix needs an explicit, persisted,
per-model negative tool-calling compatibility signal. This repo currently has
persisted privacy assessments with source provenance and freshness, but no
equivalent persisted tool-compatibility evidence plane. Shipping a hardcoded
denylist, a message-sniffing retry, or an invented metadata heuristic would
have violated the repository's evidence-honesty rules.

The next complete, orthogonal unit was therefore issue
[#927](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/927):
capture and expose real per-model `max_output_tokens` and `context_window`
metadata from discovery.

### Issue #927 root-cause closure completed locally

Reused worktree: `../commercial-loop-20260831-issue927-root` at commit
`9257de4b3f950dc2cf813cbdae37f215461c5581`,
`fix(discovery): persist provider token ceilings and context windows`.

What the completed unit now does:

- extends `DiscoveredModel` and `ModelAgent` with distinct
  `max_output_tokens` and `context_window` fields
- parses explicit limit metadata from current provider discovery sources
  instead of guessing:
  `top_provider.max_completion_tokens` and `context_length` for OpenRouter;
  `limit.output` and `limit.context` for Models.dev-enriched providers; and
  explicit completion/context fields from configured-gateway model info only
  when all deployments for one logical model agree
- preserves the two fields through agent JSON, durable pool persistence, CLI
  `discover-models` output, and the public API contract
- clamps only explicit outgoing output-budget request fields
  (`max_tokens`, `max_completion_tokens`, `max_output_tokens`) to a known
  per-agent `max_output_tokens`, without substituting `context_window`

Focused and proportional verification run on the exact local head:

- `uv run pytest tests/test_model_discovery.py tests/test_provider_catalog_store.py tests/test_discover_models_cli.py tests/test_orchestrator_client_boundaries.py tests/test_agent_pool_db.py`
  -> `156 passed in 12.06s`
- `uv run pytest tests/test_api_contract.py`
  -> `7 passed in 2.88s`

Total exact local evidence for this unit: `163 passed` across the touched
discovery, persistence, client-boundary, CLI, and contract surfaces.
## 2026-08-30 provider-catalog-sync: no scheduled run has succeeded in 5 days over one provider; workflow check was too strict

`provider-catalog-sync.yml` (run `33312773022`, job `99260685380`) failed with `credential
inventory mismatch: ['BYTEZ_API_KEY']`. Traced to `bootstrap_provider_catalog_runtime`
(`contextual_orchestrator/provider_catalog_bootstrap.py`): it registers all provider credentials up
front, and per-provider discovery failures (an entry in `errors`, or zero live models matching that
provider/credential pair) roll the credential back to its previous KV value via
`_restore_provider_credentials_atomically` — for a run-scoped ephemeral KV that previous value is
`None`, so the credential is deleted again. `registered_credentials` on the final report is then
filtered to `durable_registered_credentials = tuple(name for name in registered if
get_credential(name) is not None)`, correctly excluding the rolled-back credential. This is exactly
the graceful degradation the function's own docstring describes ("retains last-known-good models for
failed providers") — but the workflow's embedded verification script asserted
`set(report['registered_credentials']) == set(PROVIDER_CREDENTIAL_NAMES)` unconditionally, with no
tolerance for a single isolated provider outage, turning every occurrence into a hard CI failure.

**Not a one-off flake.** `list_workflow_runs` for this workflow (runs #4-#49, `2026-08-25T09:01:27Z`
through today's #49 at `2026-08-30T12:55:16Z`) shows 44 `failure` / 1 `cancelled` / 1 `skipped` — zero
successes since the schedule started, across both the 43 `schedule`-triggered runs (42 failure, 1
cancelled) and the 3 manual `workflow_dispatch` runs (2 failure, 1 skipped). The only `success` runs
(#1-3) were `pull_request`-triggered before the workflow went live on `main`. This had gone unnoticed
for 5 days of continuous near-hourly failures — itself evidence that a hard-fail-on-any-provider-hiccup
design was not actually serving as a useful signal.

**Bytez code path checked for a false-positive bug** (`contextual_orchestrator/model_discovery.py`
`PROVIDER_MODEL_SOURCES`/`_parse_bytez`/`discover_provider_models`): URL
(`https://api.bytez.com/models/v2/list/models?task=chat`), prefix-free `Authorization: <token>` header, and
response parsing all look correct and match this repo's stdlib `urllib` discovery convention used by
every other provider; nothing there would unconditionally reject every response. No `BYTEZ_API_KEY`
is available in this sandbox to replay the exact authenticated call, but an unauthenticated live probe
of the same endpoint returned a fast, well-formed `401 {"error":"Unauthorized"}` (not a 500), showing
the endpoint itself is reachable and enforcing auth normally right now. Independent corroborating
evidence from earlier the same day, a completely different code path (`ContextualWisdomLab/.github`'s
`noema-review` sidecar, which vendors this repo's discovery code) logged
`provider_discovery_failed provider=bytez code=http_status_500` (see the entry below). A real
`http_status_500` from Bytez's own backend, reproduced independently, is a stronger signal than a
one-off flake — but five straight days with zero successes is also too long/consistent to be an
ordinary transient outage; it's most consistent with a persistent problem specific to Bytez's handling
of this account/key/query shape (or, less likely, a quietly invalid `BYTEZ_API_KEY` secret returning
500 instead of the clean 401 an actually-wrong key gets from the same endpoint). Not resolvable from
this repo alone — needs an operator check of the Bytez account/dashboard for this credential.

**Fix applied, PR [#928](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/928)**
(`contextual_orchestrator/provider_catalog_bootstrap.py`,
`.github/workflows/provider-catalog-sync.yml`): a new
`evaluate_provider_credential_inventory()` — real, unit-tested production code, not YAML-inline
branching — judges a credential missing from `registered_credentials` and still hard-fails every case
that must not be silently swallowed:

- the secret was never supplied to the job at all (`environ` empty — a real configuration gap);
- the report gives no `providers_with_errors` evidence tying the rollback to a discovery failure (an
  unexplained rollback, which could hide a real bug elsewhere);
- **the rollback isn't classified as a genuinely retryable, transient condition** —
  `ProviderDiscoveryError.error_code` (already computed by
  `model_discovery._provider_discovery_error_code`, just previously discarded before reaching the
  report) is now bucketed into a small report-safe classification
  (`provider_error_classifications`), and `evaluate_provider_credential_inventory` default-denies:
  only `transient_failure` is tolerated, everything else hard-fails. `transient_failure` is
  deliberately narrow — a rate limit (`http_status_429`), a request-timeout status
  (`http_status_408`), any `http_status_5xx`, or a below-HTTP-layer `timeout`/`transport_error` — the
  set standard retry semantics call retryable. `authentication_failure` (`http_status_401`/`403`), a
  persistent non-auth 4xx (`http_status_400`/`404`/…), an unparseable response (`invalid_response`), a
  successful-but-empty listing, and anything unrecognized all collapse to `unknown_failure` and
  hard-fail. An invalid/expired credential or a permanently broken integration (wrong endpoint,
  malformed request shape, a provider that moved/retired the API) must never be excused as a
  transient blip: left alone, either would let that provider stay silently disabled forever, no
  alert, every run;
- **more than one provider is affected at once** — bounded at exactly one provider
  (`max_tolerated_missing_providers=1`) so a broader outage (several providers degraded
  simultaneously) still fails instead of reporting success while serving a stale catalog. The bound
  counts every provider whose discovery failed this run — both providers that actually lost their
  registered credential (`registered_credentials` no longer has the name) and providers whose
  credential was restored to an old-but-still-valid durable value and therefore never dropped out of
  `registered_credentials` at all (see the third review round below). A provider that merely logged
  any error with no corresponding rollback at all still does not count against the bound — the bound
  is about discovery failures with rollback evidence, not raw error-log noise.

Only when a single provider's credential is missing, the secret was supplied, and its classification is
exactly `transient_failure` does the job print a `::warning::` (with `providers_with_errors`,
`catalog_refresh_failure_count`, `restored_credentials`) and succeed — matching what the bootstrap
design already promises: the pool keeps serving from last-known-good/other-provider models. The
existing `catalog_model_count`/`eligible_model_count`/`selected_agent_ids` checks are unchanged and
still fail the job if the pool itself is unhealthy.

**Four review rounds, not one.** The first cut only checked whether…37107 tokens truncated…s and docstring `95.9%`, below the 100% standard. Decision: `WAIT_AND_REMEDIATE`. |
| [#770](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/770) | `7494f227d0ca84f65ccaac6af9614c59d1fc233b` | ready, based on [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768) | Current stack consumes the shared ordinary-chat classifier and price-honest provider-diverse selection. The latest exact head removes a trailing blank line from the doctoring record; focused discovery/bootstrap/model-selection proof is `32 passed`, and Ruff/compileall/diff-check pass. Hosted Checks must regenerate on this exact head; obtain independent current-head approval before protected merge. |
| [#769](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/769) | `9654c285c54443acf6358193925f4e0e8ae501ce` | ready, based on main | Core repository workflows succeeded on this head; obtain exact-head independent approval and remaining protected contexts. |
| [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768) | `88fee976ca4222309f625058a6f95f09e66744ec` | exact head verified; hosted checks terminal except Trivy/Scorecard neutral; approvals `0` | Current capability boundary includes ShieldGemma, legacy Completions, direct-run regressions, and exact `/v1/responses` normalization. Current head has `21` successful, `8` skipped, and `2` neutral infrastructure findings because the code-scanning baseline reports missing main-branch workflow configuration; the repository delegates those gates to central required workflows. No source failure or unresolved current-head finding was found, but protected independent approval remains required. Decision: `WAIT_AND_REMEDIATE`. |
| [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765) | `a4e4f683e3a4f39fc740b9028158da7e7c2bc219` | ready, based on main | Exact head closes the Strix SSRF finding: empty URL userinfo is rejected by presence across discovery, origin, low-level transport, and provider URL validation; empty fragments are rejected as well. Concurrent remote security coverage was preserved. Focused proof is `103 passed` across PR regressions, discovery, local gateway, and security hardening; full exact-head proof is `1519 passed in 556.04s`, with compileall/diff-check clean. The later Devin Responses-batch report was revalidated against the pre-coordinator 400 guard and closed with `13 passed` routing-contract tests without a source change. Hosted Checks are queued on this exact head and independent approval remains required. |
| [#764](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/764) | `ea5ab0e932a299640275fd98ef83ad462e46e2c0` | ready, based on [#770](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/770) | Current remote stack owns durable five-provider credentials and normalized catalog persistence; the latest docs bind bootstrap success to durable KV registration after rollback. Current-head catalog/bootstrap proof is focused `14 passed`; the code-equivalent prior head had full `1542 passed`. Hosted Checks and independent approval remain required. |
| [#763](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/763) | `531c74f49f228929425b485838f18e355aaa0cdf` | ready, based on [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765) — parent advanced to `a4e4f683e3a4f39fc740b9028158da7e7c2bc219` | Current stack integrates #765 and #768 gateway/capability boundaries with one-shot local Responses translation, local concurrency coordination, concrete-model stickiness, adaptive provider failover, an embedding-specific capability filter, and the parent’s direct sampling contract. The prior `150 passed`/`1589 passed` proof belonged to the pre-repair parent base and does not transfer; current hosted Checks and independent approval remain required. |
| [#762](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/762) | `8f87bcaeddff0866e26900e41deeafe208d8f9e4` | ready, based on main | The exact-head ADR closes the documented purpose, classification, AEAD/KMS, migration, and audit-gate review gaps; merge the design only after current-head independent approval, then implement its acceptance criteria separately. |

### Live recheck continuation — 2026-08-21 21:48 KST

The following rows supersede the corresponding snapshot rows above for the
listed PRs. This continuation preserves the older snapshot so predecessor
evidence cannot be mistaken for current-head evidence.

| PR | Current exact identity | Live gate evidence and decision |
|---:|---|---|
| [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765) | head `537915715c4b050d4b5fa18ce2b7559080c675ba`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 22 check-runs (`7` skipped, `15` queued), formal approval absent. The latest review dispositions and stacked repairs are recorded in the PR; queued checks and no approval keep the normal merge gate closed. Decision: `WAIT_AND_REMEDIATE`. |
| [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768) | head `88fee976ca4222309f625058a6f95f09e66744ec`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 31 terminal runs (`21` success, `8` skipped, `2` neutral), formal approval absent. Neutral Trivy/Scorecard results are infrastructure-baseline warnings, not source success. Decision: `WAIT_AND_REMEDIATE`. |
| [#771](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/771) | head `cc806cdb809068b78388d843758086747a21750a`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 22 check-runs (`7` skipped, `15` queued), formal approval absent. Local follow-up `276ed4f0` is not remote evidence: its normal push was rejected by the active required-workflow ruleset. Decision: `WAIT_AND_REMEDIATE`. |
| [#807](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/807) | head `f0d44f78f820f4ee34280294115e13d2ed541e14`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 22 check-runs (`7` skipped, `15` queued), formal approval absent. Local cleanup `e898ce0a` removes an unreachable error branch and passed 104 targeted tests, but normal push was rejected by the active ruleset. Decision: `WAIT_AND_REMEDIATE`. |
| [#810](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/810) | head `513a8157e667a6adbe7b91b5e802887a55fe9cd8`, base `537915715c4b050d4b5fa18ce2b7559080c675ba` | Open, non-Draft, mergeable but blocked; 17 check-runs (`8` skipped/completed, `9` queued), formal approval absent. Local follow-up `7929f707` preserves budget stops during generated planning; full local suite passed `1646` and compileall/actionlint/diff-check/Semgrep/pip-audit were clean. Normal push was rejected by the active ruleset. Decision: `WAIT_AND_REMEDIATE`. |
| [#811](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/811) | head `f0b0dd565f93d8f4aa90ca6ad67544c6b6b8051f`, base `cc806cdb809068b78388d843758086747a21750a` | Open, non-Draft, mergeable but blocked; review decision `REVIEW_REQUIRED`, no formal approval, and 17 check-runs (`8` skipped/completed, `9` queued). Exact-head focused provider/tool tests passed `115`; this is a dependent stack item over #771. Decision: `WAIT_AND_REMEDIATE`. |
| [#812](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/812) | head `dffa870589f464bd674bc64cd0c16334b5e48712`, base `f0d44f78f820f4ee34280294115e13d2ed541e14` | Remote follow-up for #807; one-file unreachable-branch cleanup, 17 check-runs (`8` skipped, `9` queued), formal approvals `0`, Devin no-issues review. Exact targeted local verification `104 passed`. Decision: `WAIT_AND_REMEDIATE`. |
| [#813](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/813) | head `6e5e19325af79c3c72eb4ff2671b3be4830068c4`, base `537915715c4b050d4b5fa18ce2b7559080c675ba` | Remote follow-up for #810; exact tree equivalent to the locally verified budget-stop repair, 17 check-runs (`8` skipped, `9` queued), formal approvals `0`. Equivalent local tree passed the full `1646`-test suite and static/security checks. Decision: `WAIT_AND_REMEDIATE`. |

### Live recheck continuation — 2026-08-21 22:38 KST

This continuation supersedes the #803 row above for its new exact head and
keeps the hosted gate separate from local evidence.

| PR | Current exact identity | Live gate evidence and decision |
|---:|---|---|
| [#803](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/803) | head `5c51c3a93bbd1779745f94502ca4d702b2e051d5`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 22 hosted check-runs (`7` completed/skipped, `15` queued), formal approval `0`, exact head unchanged since the follow-up push. Local exact-head evidence is `1451 passed`, focused PII/persistence/admin `23 passed`, `pii_protection.py` 100% statement/branch, repository aggregate 90% statement with 146 partial branches, interrogate 95.9%, pip-audit clean, Semgrep 0, actionlint/compileall/diff-check clean. Authorization-decision churn is now isolated from substantive audit retention; undecryptable replay rows degrade individually. Decision: `WAIT_AND_REMEDIATE`. |

### Live stack continuation — 2026-08-21 22:45 KST

Normal non-main stack transitions observed after the previous recheck:

| PR | Current exact identity | Live gate evidence and decision |
|---:|---|---|
| [#764](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/764) | head `ea5ab0e932a299640275fd98ef83ad462e46e2c0`, base `6b603efeb9728d7c142f090153925948c0f1248f` | Normal merge into non-main stack branch completed at merge commit `074f0e4425de4714aeecc9ee56d9f8e512c2c2e6` after exact recheck: `CLEAN`, 25/25 terminal checks, failures `0`. Decision: `NORMAL_MERGE`. |
| [#770](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/770) | head `074f0e4425de4714aeecc9ee56d9f8e512c2c2e6`, base `88fee976ca4222309f625058a6f95f09e66744ec` | Automatic normal stack transition completed at merge commit `84b010a56524b97bc9f507f016501ce5bd855d84` after #764 advanced its parent branch. This is non-main stack integration, not protected-main release evidence. Decision: `NORMAL_MERGE`. |
| [#796](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/796) | head `dc3302dd53a2aa397f19e567923f4febfa217356`, base `1968998dabf48d9558c3cc62b32937f745d11be8` | Normal merge into non-main stack branch completed at merge commit `820ac3b76934e345fb79133a269fc2c44dd7e351` after exact recheck: `CLEAN`, 25/25 terminal checks, failures `0`. Decision: `NORMAL_MERGE`. |
| [#795](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/795) | head `820ac3b76934e345fb79133a269fc2c44dd7e351`, base `48a8c79481ebf42749418c7b1d93d8553c9fb4b7` | Parent stack head advanced after #796; current state is `UNSTABLE` with no current hosted check-runs, so prior child evidence is not reused. Decision: `WAIT_AND_REMEDIATE`. |
| [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768) | head `84b010a56524b97bc9f507f016501ce5bd855d84`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Main-target root now includes the #764/#770 stack merge; open, non-Draft, mergeable but blocked, 22 checks (`7` terminal, `15` queued), review required and formal approval absent. Decision: `WAIT_AND_REMEDIATE`. |

### Live recheck continuation — 2026-08-21 23:09 KST

This continuation supersedes the prior #803 entry for its new exact head and
keeps local verification separate from the still-pending protected gate.

| PR | Current exact identity | Live gate evidence and decision |
|---:|---|---|
| [#803](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/803) | head `606eb3788681bf04928c5be9325f2ca499412069`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 24 hosted check-runs (`7` completed/skipped, `15` queued, `2` review-provider contexts), failures `0`, formal approval `0`. The latest rate-limit retention finding was verified against the bounded `authorization` stream; the exact durable-retention regression test passed. Local exact-head evidence is `1453 passed in 523.18s`, focused PII/persistence/security `43 passed`, PII protection `100%` statement/branch, repository aggregate `90%` statement with `146` partial branches, interrogate `95.9%`, pip-audit clean, Semgrep `0`, actionlint/compileall/diff-check clean. Decision: `WAIT_AND_REMEDIATE`. |
| [#801](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/801) | head `eb9ec5f4e3f8ecbcf96cb132f58a212981ff0a6d`, recorded base `39072a654261c3570496849bb4da1e2c340e2fbc`; live parent branch `70f8b4dbb6b8d5749140581c50bcdf3b31ad8475` | The requested explicit-argv CLI change and regression test are already present in the live parent tree. The stale PR head was not pushed or merged; `CLEAN` against the recorded base is not current-parent evidence. Decision: `WAIT_AND_REMEDIATE` as a no-op stack item. |

PR [#791](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/791) was merged into its stacked base branch on 2026-08-20. PR [#800](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/800) was closed unmerged and superseded by [#801](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/801). PR [#779](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/779) was merged into the #765 parent branch at `a4e9a780a56c08e131367f3b904f5c855b3a1b33`; PR [#778](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/778) was then merged into the same #765 parent branch at `0a3ab0b901d0b39d610f26538243bb5b3c1b3c61`; PR [#781](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/781) was merged into the #780 parent branch at `30476b3365ad9825a6dd2b35ac5ee10ef3c34879`; PRs [#776](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/776), [#783](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/783), and [#787](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/787) were merged into their non-main stack branches with merge commits `3e6c4205e707eee70387bb429866b689de848753`, `637e941fd9237780d2fe90150514b048d1675387`, and `41c0c87ef4c4cf335b71d07b990734944db4b89e`. None is a protected-main release. PR [#774](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/774) was closed unmerged as the stale-base predecessor of [#779](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/779). Its local
or predecessor-head evidence does not transfer. Issue [#745](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/745) is represented by
[#772](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/772) and issue [#567](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/567) by [#771](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/771). A draft or implementation PR is not treated as
completed until the protected-main contract is satisfied.

### Live exact-head continuation — 2026-08-22 01:19 KST

This continuation supersedes older rows for the listed PRs. Hosted gate
evidence and local verification are intentionally kept separate; no predecessor
head or approval is reused.

| PR | Current exact identity | Live gate evidence and local verification | Decision |
|---:|---|---|---|
| [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765) | head `d19e3492192e21e4a040fa3fc13a0793443731bf`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 19 success, 8 skipped, 2 neutral, and 1 queued check-run; approvals `0`. Exact local full suite `1729 passed`, focused suite `78 passed`, aggregate statement/branch coverage `92%`, and interrogate `100%`. Static/security evidence was recorded on the immediately preceding equivalent tree; the current three-file cleanup/assertion delta has no new gate result. | `WAIT_AND_REMEDIATE` |
| [#804](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/804) | head `71895c7f1f1d63a55e5f67d75dbd8408f8e608f9`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 17 success, 7 skipped, 2 neutral, 1 in progress, and 1 queued check-run; approvals `0`. A normal revert removed the accidental downstream #784 merge, restoring the bounded five-file root tree `a29ae0252f3bf13e70da0a32a38eca116350aad8`; exact local full suite `1436 passed`, focused suite `56 passed`, compile/actionlint/diff/Semgrep/interrogate/pip-audit checks passed. Coverage was not rerun on this exact head. | `WAIT_AND_REMEDIATE` |
| [#807](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/807) | head `d5122a0a30b4543ac2778a1c71e9ee079cbd699f`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 15 success, 7 skipped, 2 neutral, 3 in progress, and 1 queued check-run; approvals `0`. Exact local merge-result tree is `ba261ab39191323f3e116d92103f00d727b10f48` with no conflict; focused suite `117 passed`, full suite `1454 passed`, aggregate statement/branch coverage `90%`, interrogate `95.8%`, Semgrep `0`, pip-audit clean, and actionlint/compileall/diff-check passed. | `WAIT_AND_REMEDIATE` |

The hosted queues and absent approvals are normal protected-path blockers, not
D1-D5 deadlock evidence. The active ruleset has no bypass actor; no force merge,
direct protected-branch push, or approval bypass was attempted.

### Live exact-head continuation — 2026-08-22 01:43 KST

The following exact-head recheck supersedes the immediately preceding rows for
these PRs. The hosted queues remain separate from local evidence.

| PR | Current exact identity | Live gate evidence and local verification | Decision |
|---:|---|---|---|
| [#803](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/803) | head `1f836527a718374585c5fde7838148cfa22765b2`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 7 skipped and 15 queued check-runs, approvals `0`. Exact local full suite `1453 passed`, focused PII/security `34 passed`, aggregate statement/branch coverage `90%`, `pii_protection.py` 100%, interrogate `95.9%`, Semgrep `0`, pip-audit clean, actionlint/compile/diff clean, and wheel build/install/import smoke passed. One valid documentation finding was fixed in this head. | `WAIT_AND_REMEDIATE` |
| [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765) | head `d19e3492192e21e4a040fa3fc13a0793443731bf`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 20 success, 8 skipped, 2 neutral, and 1 queued check-run; approvals `0`. Exact local full suite `1729 passed`, focused suite `78 passed`, aggregate statement/branch coverage `92%`, interrogate `100%`. | `WAIT_AND_REMEDIATE` |
| [#804](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/804) | head `71895c7f1f1d63a55e5f67d75dbd8408f8e608f9`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 19 success, 8 skipped, 2 neutral, and 1 queued check-run; approvals `0`. The bounded root tree and exact local suite/static evidence remain as recorded above. | `WAIT_AND_REMEDIATE` |
| [#807](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/807) | head `d5122a0a30b4543ac2778a1c71e9ee079cbd699f`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 15 success, 7 skipped, 2 neutral, 3 in progress, and 1 queued check-run; approvals `0`. Exact local full suite `1454 passed`, focused suite `117 passed`, aggregate statement/branch coverage `90%`, interrogate `95.8%`, Semgrep `0`, pip-audit clean, and actionlint/compile/diff clean. | `WAIT_AND_REMEDIATE` |
| [#773](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/773) | head `1ec2ab6315341ad576fe1d1c27f6cbeaab1111dc`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 10 success, 8 skipped, 2 neutral, 3 in progress, and 4 queued check-runs; approvals `0`. The baseline update was normally pushed and its current hosted gate remains incomplete. | `WAIT_AND_REMEDIATE` |

None of these states establishes a D1-D5 deadlock: current heads have generated
checks or are awaiting normal approvals, and the active ruleset exposes no
bypass actor.

### Queue triage continuation — 2026-08-22 01:45 KST

New or newly relevant queue items were checked after the root rows above.

| PR | Current exact identity | Live evidence and dependency decision |
|---:|---|---|
| [#817](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/817) | head `8235d32839148c133ec046d6d16b944ff558c452`, base branch `fix/agent-pool-boundary-current` at `71895c7f1f1d63a55e5f67d75dbd8408f8e608f9` | Open, non-Draft, mechanically clean, 37 files (`+2389/-129`), but no check-runs and no formal approval. It is downstream of the still-unmerged #804 root and remains `WAIT_AND_REMEDIATE`; no downstream merge was attempted. |
| [#818](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/818) | head `057530e6f9a90ec1909e197c23304a031b0e35f6`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; current hosted `osv-scan` fails because the inherited central security workflow invokes deprecated `--output` and then rejects empty `old-results.json`/`new-results.json`; this is not a telemetry-source finding. Formal approvals `0`; decision `WAIT_AND_REMEDIATE` pending central repair and re-run. |
| [#809](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/809) | head `756d2a76bb91c0c65aac6c15bbab8270dd0ea479`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 21 success, 8 skipped, 2 neutral check-runs, approvals `0`. Despite terminal checks, the required approval gate is absent; `WAIT_AND_REMEDIATE`. |
| [#806](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/806) | head `10b87361cff4f4ed5a5d0dd17baee3e840f53b01`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open, non-Draft, mergeable but blocked; 21 success, 8 skipped, 2 neutral check-runs, approvals `0`. Despite terminal checks, the required approval gate is absent; `WAIT_AND_REMEDIATE`. |

### Live exact-head continuation — 2026-08-22 01:48 KST

The bounded documentation/test PRs were independently reviewed at their
current heads. Hosted terminal success does not replace the required approval.

| PR | Current exact identity | Local and live evidence | Decision |
|---:|---|---|---|
| [#806](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/806) | head `10b87361cff4f4ed5a5d0dd17baee3e840f53b01`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | One-file test-only diff; exact focused tests `8 passed`, compileall and diff-check passed. Hosted: 21 success, 8 skipped, 2 neutral; approvals `0`. | `WAIT_AND_REMEDIATE` |
| [#809](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/809) | head `756d2a76bb91c0c65aac6c15bbab8270dd0ea479`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Two-file public-docstring diff; exact interrogate `100.0%`, compileall and diff-check passed. Hosted: 21 success, 8 skipped, 2 neutral; approvals `0`. | `WAIT_AND_REMEDIATE` |

### Protected auto-merge continuation — 2026-08-22 01:50 KST

Normal squash auto-merge is enabled for #804, #803, #765, #807, #806, and
#809 at their exact heads. GitHub reports each as `blocked` until required
reviews and hosted gates are satisfied; this does not bypass any protection.
Downstream #817 remains unqueued for merge until root #804 advances.

All links and full commit SHAs in the initial snapshot reflect the remote state
observed at 2026-08-21 15:36 Asia/Seoul; they are evidence pointers, not
standing approval.

### Live model-group continuation — 2026-08-25 09:12 KST

| PR | Current exact identity | Live evidence, customer outcome, and gap |
|---:|---|---|
| [#834](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/834) | head `6b069a059b677bbb367e80e5819f34564673fa4a`, base `50014ef9f87623c6dfd529116297c5d180743125` | Open, non-Draft, blocked for protected review/checks; all six review threads are resolved on this exact head, hosted jobs are queued, and no independent approval exists. The feature adds arbitrary operator-defined logical model groups (names need not resemble member model IDs), authenticated REST CRUD, Agent Pool DB persistence, measured intra-group provider routing, OpenRouter/OpenCode Zen discovery, explicit free-cost classification, Admin evidence, OpenAPI, and APA-grounded ADR 0026. Discovery never infers equivalence and no model family is built in. Exact current-head local evidence: full suite `1586 passed in 604.40s`; focused REST/group/discovery/governance suite `37 passed`; new `model_group.py` statement and branch coverage `100%`; compileall and diff-check clean. Customer-visible remaining gap: multi-replica measurement aggregation requires a normalized time-windowed observation store and explicit retention/decay policy; unknown provider prices must remain unknown. Decision: `WAIT_AND_REMEDIATE`. |

The model-group boundary is deliberately generic. Discovery never infers
equivalence from similar names; authenticated operators assert group membership
through `/api/v1/model_groups`, after which routing ranks the logical group
before selecting a measured provider member.

### External central workflow prerequisite

At the refreshed snapshot, central scheduler PR [#1178](https://github.com/ContextualWisdomLab/.github/pull/1178) is open at exact head `97b084ac28b5ccf6de7f68fd2e019d8da6f80143`. Its target caller runs at minute `17`, uses non-cancelling concurrency, scans at most 50 PRs, dispatches at most one repair, and forwards only `PR_REVIEW_MERGE_TOKEN`/`OPENCODE_APPROVE_TOKEN`; current hosted Checks are pending and the cancelled queue scan is not a terminal failure. For reproducible external evidence, the scheduler source is pinned to [`ContextualWisdomLab/.github@8cb6a1a34e9f5c3d4634b94599f492049185bc0d`](https://github.com/ContextualWisdomLab/.github/commit/8cb6a1a34e9f5c3d4634b94599f492049185bc0d), which contains [`.github/workflows/pr-review-merge-scheduler.yml`](https://github.com/ContextualWisdomLab/.github/blob/8cb6a1a34e9f5c3d4634b94599f492049185bc0d/.github/workflows/pr-review-merge-scheduler.yml) and [`.github/workflows/pr-review-fix-scheduler.yml`](https://github.com/ContextualWisdomLab/.github/blob/8cb6a1a34e9f5c3d4634b94599f492049185bc0d/.github/workflows/pr-review-fix-scheduler.yml). Related central gateway PR [#1170](https://github.com/ContextualWisdomLab/.github/pull/1170) is open at exact head `1f2b93ead7205b33712de1865d84c004d93be7ed` and records target [#790](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/790) at current exact head `8d31fa50cc6de8ddc3e6b91576e7251c5aa7d914`; its own protected Checks and independent approval remain pending. The target repository snapshot [`ContextualWisdomLab/contextual-orchestrator@36e3be0bca5f64b7c5150351b2d505ea536a46a4`](https://github.com/ContextualWisdomLab/contextual-orchestrator/commit/36e3be0bca5f64b7c5150351b2d505ea536a46a4) has no `.github/workflows/opencode-review.yml`; the central queue remains asynchronous. Superseded [#1183](https://github.com/ContextualWisdomLab/.github/pull/1183) is closed without merge, so its head is not integration evidence.

The scheduler's earlier dry-run decision for PR #787 was `review_dispatch` for its non-main base; #787, #779, and #778 are now merged into the #765 parent stack. The target repository currently exposes no `opencode-review.yml` workflow of its own and the central repository-dispatch queue remains asynchronous. Until #1178 and gateway #1170 reach protected main, remaining stacked PR review may remain absent or use the prior central model path; this is an external integration dependency, not evidence that the stacked code is merge-ready.

Central Strix context repair is now owned by [.github#1153](https://github.com/ContextualWisdomLab/.github/pull/1153) at exact head `035343c8a68e880a4abf27f7c947bfed9dbaafcf`; its canonical local gate suite passed, while protected hosted Checks and independent approval remain pending. Duplicate follow-ups [.github#1191](https://github.com/ContextualWisdomLab/.github/pull/1191) and [.github#1192](https://github.com/ContextualWisdomLab/.github/pull/1192) are closed and must not be treated as active integration evidence.

### Central exact-head continuation — 2026-08-22 02:05 KST

The prior central snapshot is historical. Current control-plane evidence is:

| PR | Current exact identity | Live evidence and decision |
|---:|---|---|
| [.github#1178](https://github.com/ContextualWisdomLab/.github/pull/1178) | merged commit `efea53a11c90c7ca519af56aed6918124f45826e` into stacked base `fix/pip-audit-pip-2621` | The hourly caller merged into its non-main base, not protected `.github` `main`. Its CodeQL merge-preview run failed because `refs/pull/1178/merge` was absent although `merge_commit_sha` existed; the failure is preserved as control-plane evidence. |
| [.github#1206](https://github.com/ContextualWisdomLab/.github/pull/1206) | head `633342d56801fdb4a9261a165bd31e94cf9a58f4`, base `ac26a07e9fe19760f3b55e3a1db4021ce4776ae6` | Follow-up fixes CodeQL merge analysis to use the exact merge SHA. Local exact suite `1297 passed`, statement/branch coverage `100%`, interrogate `100%`, focused contract `3 passed`, actionlint/compile/diff clean. Hosted state: 5 queued, 5 skipped, approvals `0`. Decision: `WAIT_AND_REMEDIATE`. |
| [.github#1170](https://github.com/ContextualWisdomLab/.github/pull/1170) | head `fa4c6faa7a8c580aca556c31b00068d7aab69010`, base `dd58a88391e44a32fb399f7407f508d8e73cc1c7` | Open main-target gateway PR; hosted state observed as 5 success, 13 skipped, 16 cancelled, approvals `0`. Decision: `WAIT_AND_REMEDIATE`. |
| [.github#1153](https://github.com/ContextualWisdomLab/.github/pull/1153) | head `ebda81f832261489289447778b0e0e7726f9741e`, base `dd58a88391e44a32fb399f7407f508d8e73cc1c7` | Open Strix repair; hosted state observed as 27 success, 15 skipped, 3 neutral, 1 failure, 2 queued, approvals `0`. Failure remains a source/control-plane finding to inspect; no merge or bypass. |

### Central exact-head continuation — live refresh 2026-08-22

The preceding rows are historical snapshots. The latest normal-path evidence is:

| PR | Current exact identity | Live evidence and decision |
|---:|---|---|
| [.github#1198](https://github.com/ContextualWisdomLab/.github/pull/1198) | head `e5a7ac882559fe6d1ae1f91e27d79bc8e0aa1e77`, base `4c33442021d63b09f35a874c5e7a779dd46ef8f2`, merge-result tree `fd7e18d2c50867bb7438325ba2fa09aaa22e204b` | Current exact stack includes the CodeQL merge-preview identity/authentication repair, trusted LLVM 19 coverage boundary, and normal protected-main restack. Fresh exact-head local evidence: `1362 passed, 1 skipped, 16 subtests`, statement/branch coverage `8394/3264 = 100%`, interrogate `100%`, relevant actionlint, compileall, diff-check, and hash-locked pip-audit clean. Current exact-head hosted OpenCode run `32528443790` / bootstrap job `96915418375` remains queued, CodeQL run `32528443855` remains queued, and Strix run `32528443763` is in progress with runner assignment. Formal approval is absent; predecessor-head evidence is discarded. Decision: `WAIT_AND_REMEDIATE`; D2 observation window is not satisfied. |
| [.github#1209](https://github.com/ContextualWisdomLab/.github/pull/1209) | head `e043ad82b8ed65cfd6f46ed844467c8ad9955665`, base `4c33442021d63b09f35a874c5e7a779dd46ef8f2`, merge-result tree `250e070a01307bf07675ab3faadcb5dec7d20c5e` | Current exact head is a normal protected-main restack of the cross-fork OSV result-isolation repair. Fresh local evidence: `1330 passed, 1 skipped, 16 subtests`, statement/branch coverage `8282/3196 (100%)`, interrogate `100%`, changed-workflow actionlint, compileall, exact hash-lock pip-audit, and diff-check clean. Hosted required checks are mixed success and pending/in-progress after the restack; formal approval is absent and unresolved current threads are `0`. Decision: `WAIT_AND_REMEDIATE`; predecessor-head evidence is discarded. |
| [.github#1203](https://github.com/ContextualWisdomLab/.github/pull/1203) | merge commit `4d3d24aa404959f5067735fec0558d5924ade590` from head `c627d4ae7a26222ed3d2ee1ded19e270930aa1f2` into stacked base `94e2b28aee2029d36f272336a7cd4e4ad1516161` | Merged normally into the non-protected #1198 stack, not protected `.github` `main`; it is not protected-main completion evidence. |
| [.github#1208](https://github.com/ContextualWisdomLab/.github/pull/1208) | closed without merge from head `9f0845517010f2c4695de83dd2bd50385c068a15`, base `fce028b4c3bf8e2e5e4819c1c5622e90cfa6ab39` | Historical successor to closed #1207; its exact local pip-audit evidence reproduced `pip==26.1.2 / PYSEC-2026-3721`, but no protected-main merge occurred. Root #1198 owns the current pip-lock repair. |
| [.github#1187](https://github.com/ContextualWisdomLab/.github/pull/1187) | head `0a88e24d9a1c92420f412d241f850aab8e72106e`, base `0156282022134484ea9d7541d5ba0730ba14fd96`, merge-result tree `05a0fdac58258bb6b30da9376c37003a8e18b609` | Normally restacked onto current protected main; one shell-test conflict retained main's targeted-dispatch assertion. Exact merge-result evidence: `1323 passed`, statement/branch coverage `8184/3172, 100%`, interrogate `100%`, compileall, shell syntax, exact hash-lock pip-audit, and diff-check clean. Hosted rollup is 21 queued/blank, 2 pending, and 13 skipped; no qualifying approval exists. Decision: `WAIT_AND_REMEDIATE` pending terminal required Checks and normal approval. |
| [.github#1188](https://github.com/ContextualWisdomLab/.github/pull/1188) | head `2c05f05f5fbb923099e0e228d616ab9974dbd327`, base `0156282022134484ea9d7541d5ba0730ba14fd96`, merge-result tree `6c19376c4a030eb97a9d4b7f6a2a0b85d38740a3` | Exact current-head evidence: `1319 passed`, statement/branch coverage `8168/3162, 100%`, interrogate `100%`, compileall, actionlint for both changed reusable OIDC workflows, shell syntax, hash-locked pip-audit, and diff-check clean. Hosted rollup is 25 success, 18 skipped, 1 cancelled, 3 neutral, and 4 queued/in-progress; no qualifying approval exists. Decision: `WAIT_AND_REMEDIATE` pending terminal required Checks and normal approval. |
| [.github#1189](https://github.com/ContextualWisdomLab/.github/pull/1189) | closed without merge from PR API head `6ffdcc3f0c96610295d143a3f54f3821b3a23ec9`, base `fce028b4c3bf8e2e5e4819c1c5622e90cfa6ab39` | Absorbed by root #1198 at exact feature-stack head `3016543f`; the normal restack `12c7d513` was pushed to its branch but was never treated as PR evidence. No protected-main merge or bypass occurred. |
| [.github#1206](https://github.com/ContextualWisdomLab/.github/pull/1206) | squash commit `b8737dadbcb9871dc939e500ecbb84ceccb8cf42`, merged into stacked base `fix/pip-audit-pip-2621` from head `d51638c11c5da1b30dd1867ecd019fd0dd28eb92f` | CodeQL merge-analysis follow-up merged normally into the #1198 stack, not protected `.github` `main`. The merge tree is `b30e5b0eea90b59eb97dd894ebb1e63a0c9b8c3b`, so it is retained as stack evidence and does not count as protected-main completion. |
| [.github#1153](https://github.com/ContextualWisdomLab/.github/pull/1153) | head `1f8878d78cb2f0aed68964ea5fabf5679526e78b`, base `fce028b4c3bf8e2e5e4819c1c5622e90cfa6ab39`, merge-result tree `9a15ef3f059f652f84f5b76d1bc8cce2f0d8bdac` | Current head is a main-refresh successor for the JavaScript/Storybook coverage gate. Hosted exact-head checks show 3 success, 11 pending, 14 skipped, and 6 cancelled, with no failure conclusion or qualifying approval. Prior local evidence at older heads does not transfer; decision remains `WAIT_AND_REMEDIATE` pending current-head verification and normal approvals. |

At the current observation, no D1–D5 emergency deadlock is established for these central PRs. Organization ruleset `18156473` (`CWL Central required workflows`) is active for normal repositories, has no bypass actors, and requires two approvals, last-push approval, thread resolution, and the listed central workflows. It explicitly excludes the `.github` repository; `.github` instead exposes repository ruleset `17921150` with zero required approvals and an `OrganizationAdmin` always-bypass actor. That bypass is not used: the maintainer procedure still requires independent substantive review, exact-head evidence, terminal Checks, and a final refetch. The queued runs above are only minutes old at this observation, so D2's six-hour/two-observation threshold is not met.

### Central queue live refresh — 2026-08-22 06:00 KST

The queue is progressing, but no terminal merge gate has been fabricated or
reused. On [.github#1198](https://github.com/ContextualWisdomLab/.github/pull/1198),
the predecessor run `32524224916` was cancelled after its bootstrap and the
current exact-head OpenCode bootstrap job `96915418375` remains queued; the
current Strix job `96915480662` has started on a hosted runner. The newer
`scan-pr-queue` failure shown by the PR rollup is also a cancelled predecessor,
not a source failure. On
[.github#1209](https://github.com/ContextualWisdomLab/.github/pull/1209),
OSV, dependency review, Noema, and the security jobs have successful current
contexts while CodeQL/Strix and the scheduler remain pending or in progress
after the restack; this is below D2's threshold. The
contextual #818 refresh created replacement current-head runs after cancelling
the prior duplicate event runs; the cancelled `opencode-review` and
`coverage-evidence` entries have no job steps or source log and are not source
failure evidence. Contextual #773 has current scheduler and Noema success but
OpenCode/Strix remain queued. These observations are all below D2's six-hour
and two-observation threshold; decisions remain `WAIT_AND_REMEDIATE`.

### Contextual live-head refresh — 2026-08-22

The older contextual PR rows above are historical unless their SHA matches this table:

| PR | Current exact identity | Live state and decision |
|---:|---|---|
| [#804](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/804) | head `92c1ef02dc3e5f99c3fee21131cc9977c2eb10d6`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465`, merge-result tree `1027c55395eb18821586749882bc2e199f3a2bbe` | Current head is a documentation-only follow-up on verified code head `4a919ce2`; the preceding exact source tree passed `1473` tests and principal-claim rotation/cross-subject regression evidence. Fresh hosted checks show security, CodeQL, supply-chain, dependency, OSV, Scorecard, Trivy, and scheduler success while Strix remains pending; formal approvals `0`, auto-merge disabled. Earlier repository-wide coverage/Ruff observations remain quality evidence for the source head and are not silently transferred to the doc-only tip. Decision: `WAIT_AND_REMEDIATE`. |
| [#807](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/807) | head `f832e32f99886388188e5b1f0d89c47ce4cfeef8`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open and mergeable but blocked; current checks are terminal at 21 success, 2 neutral, and 8 skipped; auto-merge enabled and formal approvals `0`. Decision: `WAIT_AND_REMEDIATE` pending required independent approvals. |
| [#818](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/818) | head `133729cfbab2ac74f3309cad8fbc7e20c2e33627`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465`, merge-result tree `ec2bee36c5e7928d8e2e141f1c7ec8eb28d5b75c` | Current head adds the buyer-safe disconnected-client diagnostics follow-up on top of the telemetry stack. Fresh exact-head evidence is `1456 passed`, statement coverage `92%`, branch-enabled total `90%` (`1018` branches, `144` partial), interrogate `93.3%`, compileall, tests-workflow actionlint, hash-locked pip-audit, and diff-check clean. Cancelled predecessor OpenCode/coverage runs had no steps or source log; replacement exact-head runs are queued, formal approvals `0`. Decision: `WAIT_AND_REMEDIATE`. |
| [#819](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/819) | head `c9ac72c4479e7709949975a2d487f3d4eb582a30`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open and mergeable but blocked; current functional/security checks are terminal with 21 success, 2 neutral, and 8 skipped results, but formal approvals remain `0`; auto-merge is enabled. Decision: `WAIT_AND_REMEDIATE`. |
| [#820](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/820) | head `83d1326f9149e84dbe58fec0739efca5da99eead`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465`, merge-result tree `390af78d97372195d73f77d0e7ebaf7484a2edbb` | Fresh exact-head evidence is focused `87 passed`, full `1446 passed`, conflict-marker scan/compileall/diff-check clean. Hosted `osv-scan` run `32527911591` / job `96913798878` reproduces the inherited central `--output` deprecation and empty-result `test -s` failure after scanner exit 0; this is not a source vulnerability. Strix remains pending/in progress and formal approvals `0`. Decision: `WAIT_AND_REMEDIATE` pending central repair and exact-head re-run. |
| [#821](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/821) | head `c5de31cf276580fddd4f3bcf863f5a7fcfa5aeb8`, base `e226e1197bdfc890c9d8e5b9b648c78857d7e465` | Open and mergeable but blocked; current functional/security checks are terminal with 21 success, 2 neutral, and 8 skipped results, but formal approvals remain `0`; auto-merge is enabled. Decision: `WAIT_AND_REMEDIATE`. |

### Backlog convergence and consolidation — 2026-08-23

All prior per-PR "Live ... continuation" rows above are historical. A global
`clean` or `merge-ready` label is deliberately not carried forward: a
protected-merge claim must be refreshed for the PR's exact current SHA,
including reviews, unresolved threads, and required checks.

**Exact protected-gate refresh — 2026-08-23.** REST inventory
(`GET /pulls?state=open`) returned **31** open PRs, not 29. The current #803
governance-audit durability repair is `5c6670cb`, with 6 active workflows out
of 29 and no failure; #804's ADR reconciliation is `d8a34558`, with 31
terminal exact-head check runs and no failure in this refresh.
#818 is `083316fc`, with one active replacement check out of 29 after the
session-correlation repair. New #824 is `a4219151`, with six active checks out
of 28 for the locked local-test entrypoint. #820 (`9cae444a`) has 30 terminal
exact-head runs with no failure. Those results are only partial gate evidence:
#803, #818, and #824 are explicitly `REVIEW_REQUIRED`, and every PR needs its
own fresh independent approvals, resolved-thread evidence, and required
terminal workflows before a normal protected merge. No PR is described here as
merge-ready while any of those facts are missing or unverified.

**Shared Strix repair blocked — 2026-08-23.** The current exact heads
[#803](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/803)
(`5c6670cb`) and [#824](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/824)
(`a4219151`) both have a terminal failing `strix` check. Their archived reports
show a rate-limited primary NVIDIA NIM attempt followed by a zero-finding NIM
fallback whose exact `MODEL QUALITY WARNING` banner was misclassified as an
infrastructure failure; this is shared-gate behavior, not zero-finding proof of
either PR's source correctness. Initial central repair
[.github#1254](https://github.com/ContextualWisdomLab/.github/pull/1254) was
closed without merge as a duplicate. Its active successor
[.github#1213](https://github.com/ContextualWisdomLab/.github/pull/1213) is
open at `8d0f7ca8`, stacked on central
[#1233](https://github.com/ContextualWisdomLab/.github/pull/1233)
(`fix/organization-loop-oidc-fallback@dfb8e261`) rather than protected
`.github/main`. It normalizes the workflow-facing `openai-direct/*` fallback
before LiteLLM dispatch and strips only an exact timestamped advisory that says
optional web search lacks `PERPLEXITY_API_KEY`; fatal, denied, timeout, and all
other warnings remain fail-closed. Direct-OpenAI `repository_dispatch` run
`32643804284` validated live #1233 metadata and found zero vulnerabilities,
but its old protected-main classifier terminally failed on seven instances of
that optional advisory; its subsequent same-head status publisher was rate
limited, so it created no success evidence. Fresh #773 head `1240bc23` then
terminally failed run `32644795368` with the same pattern: zero NIM findings,
then raw `openai-direct/gpt-5.6-luna` rejected by LiteLLM as an unknown provider;
it emitted no source vulnerability. #1213's exact `8d0f7ca8` run `32644636757`
likewise scanned its three changed files without a vulnerability before the
trusted pre-#1213 gate passed that same raw alias to LiteLLM. Because both
`pull_request_target` and `repository_dispatch` deliberately execute a trusted
base gate rather than the PR-head gate, the unmerged #1213 cannot change its
own protected scan behavior. Executing the PR-head gate with credentials,
fabricating a status, or using a bypass would violate the boundary. A
human-authorized non-bypass bootstrap decision, then fresh exact-head Strix
evidence, normal stack integration, independent approvals, and fresh target
checks remain required. Neither target PR is protected-main evidence or
unblocked before those conditions hold.

**Closed technical gap — unauthenticated denial recording on the durable
persistence hot path (found and fixed in #803).** While triaging #803's
review threads, tracing `server.py`'s `_authorize` into
`orchestrator.py`'s `_StateStore.save()` showed that `record_authorization_decision`
fires on every pre-auth denial (401 unauthorized, 429 rate-limited — both
reachable with zero credentials), and, when `--state-db` is configured, that
routed through a synchronous, lock-serialized sqlite commit shared with
durable `workflow_run`/`evaluation_run` persistence. An attacker spraying
denied requests across rotating source IPs (evading the per-IP rate limit)
could force that lock contention against legitimate authenticated traffic — a
real DoS amplification this PR introduced, not a pre-existing one, since
denied requests were never durably written before it. Fixed by splitting
`_StateStore.save()` by durability need: keyed kinds stay synchronous, stream
kinds (audit/authorization/analytics — already bounded/best-effort by
existing retention limits) now queue through a bounded background worker,
reusing the `NonBlockingLedgerStore` pattern already established in
`cost_ledger.py` for the same problem class. Verified with two new regression
tests and the full local suite (1459 passed) before and after; no observed
behavior change for `load()`/`close()` read-after-write or restart-durability
guarantees.

## 5. Open issue and product-gap queue

| Issue | Customer-visible gap | Planned proof / next PR |
|---:|---|---|
| [#568](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/568) | Closed by merged PR [#785](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/785): operators can compare provider-neutral reasoning profiles at equal budget. | Keep production route/conduct defaults locked until the accepted true-parameter ablation evidence permits a separately authorized default change. |
| [#123](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/123) | A sole collaborator can be unable to satisfy last-push approval. | Add governance evidence/runbook or a protected-rule-compatible process; never bypass approval. |
| [#119](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/119) | Ambiguous or unbounded inbound framing threatens request integrity. | The #776/#783 implementation stack is merged into non-main branches; protected-main integration still requires exact-head hosted evidence and independent approval. |
| [#118](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/118) | Liveness and authenticated readiness are not yet fully separated. | PR [#780](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/780) implements the minimal `/healthz` and authenticated `/readyz` contract; merge only after exact-head Checks and independent approval. |
| [#117](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/117) | Trace access and inference access need separate authority. | PR [#780](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/780) merged the minimal liveness/readiness and trace-authority slice; the issue remains open for batch ownership, full purpose/tenant/resource/lifetime/revocation context, and the single-token migration gate. |
| [#116](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/116) | Browser admin sessions need separation from long-lived bearer credentials. | PR [#788](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/788) implements opaque bounded sessions, Secure-by-default cookies, same-origin state-change checks, logout/revocation, and regression evidence. |
| [#103](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/103) | Release readiness must fail closed on stale head, missing review, or missing Checks evidence. | PR [#784](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/784) merged the semantic split, but the issue remains open until a trusted `.github` producer artifact and consumer verification bind complete exact-head policy evidence; caller-supplied dictionaries remain insufficient. |
| [#899](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/899) | CEFR writing/speaking observations need a governed, evidence-bound orchestration boundary. | PR [#903](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/903) is the current implementation head; validate its exact protected checks, research traceability, and independent approval before delivery. |
| [#897](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/897) | Language-rater output must structurally prohibit final CEFR or placement decisions. | Keep the operation limited to criterion observations and evidence references; align the acceptance contract with PR #903 and the downstream CEFR/fast-mlsirm owners. |
| [#102](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/102) | Equivalent endpoints need race-to-first-valid completion without unsafe cancellation. | Closed predecessor [#114](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/114) is explicitly a partial experiment and its evidence does not transfer. Rebuild one bounded vertical slice after the protected provider boundary is integrated: explicit endpoint equivalence, completed-response validation, bounded budgets, cancellation-or-drain, deterministic tie-breaking, secret-redacted attempt provenance, and provider-truth tests. |
| [#86](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/86) | NVIDIA NIM discovery needs live, evidence-grade capability/cost/quality measurement. | PR [#906](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/906) is the active benchmark implementation; its local and ordinary hosted evidence passes, but OpenCode is missing a current verdict and Strix failed closed on provider HTTP 500s. |

Issue [#95](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/95) (Atheris locking must work on all supported CPython interpreters) was closed 2026-08-23 as resolved on protected main by a simpler mechanism than the PR #96 predecessor originally proposed: `pyproject.toml`'s `fuzz` extra pins one version (`atheris==3.1.0; python_version >= '3.12'`) rather than a two-way version split, and it already covers both the 3.12 fuzz runner and the central 3.14 coverage-evidence image per `.github/workflows/fuzz.yml`'s own comment — verified directly against the exact current head, not assumed from the stale issue history. GitHub currently returns `404 Not Found` for issue [#777](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/777); its earlier metric-gap
row is therefore removed from the actionable queue rather than treated as a
live work item.

## 6. Prioritized gap register

| Priority | Gap | Current evidence | Definition of done |
|---:|---|---|---|
| P0 | Protected delivery cannot merge a PR until its exact current SHA has the required approvals, resolved threads, and terminal workflows; `.github` has a weaker repository-local rule than the organization rule. | Organization ruleset `18156473` requires two approving reviews, an additional approval for unattributed changes, last-push approval, and resolved threads for normal repositories. It excludes `.github`, whose active repository ruleset `17921150` permits zero required approvals and exposes an OrganizationAdmin bypass; the maintainer procedure forbids that bypass and retains the stronger independent-review gate. The 2026-08-23 exact refresh found 30 open PRs, including #803 with replacement workflows active after a security fix. This baseline makes no repository-wide clean/ready inference from partial checks; see "Exact protected-gate refresh" above. | Align `.github` governance with the organization policy or document an equivalent non-bypass gate; then obtain independent approvals for the exact current SHA, resolve threads, pass hosted required workflows, and complete normal squash/merge. Upstream: raise the shared installation's rate ceiling or shard review-dispatch load off the single token, since per-PR remediation cannot fix a saturated shared credential. |
| P0 | Agent-pool resource paths must not let a caller dereference a worker outside its addressed pool. | Strix reported the recurring IDOR on exact PR #784; direct root repair [#804](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/804) is open with the pool-boundary resolver and regression tests. #784 now stacks on #804 for dependency-safe retesting. | Protected #804 merges to main, then affected stacked PRs retain the root base and rerun Strix on their exact current heads. |
| P0 | Provider boundary is still being assembled across stacked PRs. | [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768), [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765), [#764](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/764), [#770](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/770), and [#763](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/763) are pending integration; #778 and #779 are integrated into #765, including temperature negotiation. Central OpenCode gateway routing is tracked by [.github#1170](https://github.com/ContextualWisdomLab/.github/pull/1170), while the current target caller is carried by [.github#1198](https://github.com/ContextualWisdomLab/.github/pull/1198); neither has protected-main completion evidence. | One current-main stack has capability isolation, secure JSON, bounded framing, multimodal evidence, KV bootstrap, honest catalog, optional-control negotiation, and failover with no duplicate logic; central review execution must use the same current gateway pin after protected integration. |
| P0 | Operational failure paths are not yet one buyer-verifiable contract. | [#771](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/771) and [#772](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/772) are open. | Exact-head full suite, focused edge tests, security scans, and a buyer-facing failure/rollback trace pass. |
| P1 | PII can remain usable without blanket masking, but authorization/encryption is unfinished. | [ADR 0010](planning/adrs/0010-pii-audit-not-mask.md) records the no-blanket-masking policy and explicitly leaves authorization/encryption as follow-up. The actual design is proposed [ADR 0011 at #762's exact head](https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/8f87bcaeddff0866e26900e41deeafe208d8f9e4/docs/planning/adrs/0011-pii-purpose-authorization-and-field-encryption.md); both design [#762](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/762) and implementation [#803](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/803) remain open and are not protected-main evidence. | Protected main has purpose-scoped caller/role authorization, field-level encryption at rest, credential-only redaction, and audit tests proving raw PII is returned only to an authorized purpose. |
| P1 | Deep-workflow compute policy lacks provider-neutral measured ablation. | PR [#785](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/785) supplies opt-in profiles, snapshot replay, and synthetic/estimated RMSE; the production gate remains closed pending buyer-held-out measurement. | Equal-budget shallow/deep/role-effort/access-list replay with reproducible quality, verifier, cost, and trace metrics. |
| P1 | Model discovery lacks live NVIDIA NIM evidence. | Issue [#86](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/86) remains open; active PR [#906](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/906) provides the bounded benchmark, but it is not protected-main evidence while OpenCode/Strix and independent approval remain incomplete. PR [#1063](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1063) source commit `9928e4ab` refreshes the expired prototype-access evidence against NVIDIA's official Run NIM Anywhere terms; its full local tree is `3394 passed, 2 skipped`, while protected exact-head checks and independent review remain required. | KV-backed NIM discovery benchmark records model-level declared capability, price provenance, failure class, and quality result without secret leakage; protected main then activates only capability-qualified deployments. |
| P1 | Release gate and hourly loop need exact operational proof. | Central scheduler workflows own the loop; PR [#784](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/784) adds the exact-head authority evaluator/collector, but protected approval and release evidence remain open. | One scheduler owner, no duplicate workflow, exact-head release gate, version/changelog update, and normal protected release evidence. |
| P2 | LineageWeave has no protected-main consumer acceptance gate. | [#801](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/801) added explicit CLI `argv` only to a non-main stack. Main-target [#823](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/823) has the explicit contract at `6bb3fe2c54cda9f574cd239922bc91ece5ea2585`, but remains `REVIEW_REQUIRED`/blocked despite terminal hosted checks; documented protected main still exposes `contextual_orchestrator.__main__.main()` without an `argv` argument. LineageWeave `main@ef6f5a5f` still assigns `sys.argv` in `docker/contextual-orchestrator/start.py`, and its bootstrap test observes that mutation; open LineageWeave [#468](https://github.com/ContextualWisdomLab/LineageWeave/pull/468) retains it. Its opt-in real-provider test bypasses that bootstrap, so neither it nor #823's mocked-server unit test is authenticated consumer proof. | PR #823 explicit CLI invocation contract is merged to protected main and update LineageWeave at that exact upstream pin to invoke the server with explicit arguments rather than mutating process arguments. Then run a LineageWeave-owned authenticated `/v1/chat/completions` end-to-end test that proves process `sys.argv` is unchanged; retain authorization and chat-completion evidence against the exact protected main SHA. |
| P2 | Ecosystem boundaries need consumer proof. | `naruon`, `.github`, and sibling components are named consumers, but this repo remains one deployable product. | test_naruon_ecosystem_connector.py proves the exact JSON schema and endpoint consumption without speculatively extracting the codebase. |
| P2 | Frontend component inventory is not applicable to the operative admin console. | An unwired `admin_ui/` React + Storybook scaffold and workspace entry exist, but the inline stdlib admin remains the served interface. | Keep the existing Figma artifact record; defer Storybook adoption until the frontend is built and wired under ADR 0033's triggers. |

## 7. Delivery gates

### Current KPI-contract delivery

The buyer-facing accuracy and decision-latency contract is proposed in
[PR #1103](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1103)
with historical snapshot `e14ee3170a4802e199316064b9ee0d3bfcc28d95`. That initial change
adds true-parameter psychometric RMSE and p95 route-decision latency to the
analytics specification; it does not change production routing defaults.
Hosted evidence at this snapshot has CodeQL compatibility green, but OpenCode
Review failed and independent approval is absent, so the contract is not yet
protected-main evidence. These check results describe only that historical
snapshot. The proposed KPI fields are not emitted by the runtime snapshot;
implementation, observed buyer measurements, and consumer acceptance remain
open. True-parameter recovery is a unit-test contract on an identified scale,
not evidence of observed buyer accuracy. Accuracy claims require observed
task outcomes; latency claims require request and decision traces rather
than outcome labels. Later PR revisions require their own verification.

For each PR, perform the following loop on the current head: inspect changed
files and review threads, reproduce the claimed behavior, fix root causes in
the shared path, run focused and full tests, run compile/diff/security checks,
refresh the hosted Checks, and merge only after the protected rule is satisfied.
Remote agent pushes are respected by refetching the head; stale approvals or
checks are not reused. Review queues and hosted wait time remain active-work
time: use it to implement the next independent gap, not to bypass the gate.

Release is not complete until the version, `CHANGELOG.md`, release candidate,
and exact-head evidence all agree. A green local run is not production or
buyer telemetry; label local evidence accordingly.

## 8. Standards and research basis (APA 7th)

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388). https://doi.org/10.48550/arXiv.2512.04388

OpenAI. (n.d.-a). *Create chat completion*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/chat/create

OpenAI. (n.d.-b). *Create a model response*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/responses/create

OpenAPI Initiative. (2025, September 19). *OpenAPI specification version 3.2.0*.
https://spec.openapis.org/oas/v3.2.0.html

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*TRINITY: An evolved LLM coordinator* (arXiv:2512.04695).
https://doi.org/10.48550/arXiv.2512.04695

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP caching* (RFC 9111).
RFC Editor. https://www.rfc-editor.org/rfc/rfc9111.html

National Institute of Standards and Technology. (2024). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

These sources support the current product shape, OpenAI-compatible wire
honesty, deep-versus-shallow orchestration allocation, cache safety, and
generative-AI risk evidence. PDFs are attached only when redistribution is
permitted; otherwise the canonical citation and link are retained.

## 9. Design and ecosystem record

- Existing editable Figma file: `Contextual Orchestrator Plugin-Driven Admin
  Design`, file ID `vsZMd8WAv42HDRgcZuNcWk`, recorded in
  [`docs/figma_artifacts.md`](figma_artifacts.md). No new Figma work is needed
  for this backend-only baseline.
- Existing FigJam architecture board is also recorded in that file.
- Storybook/`ui-ux-pro-max`/`Anti-Slop-UI` are deliberately deferred, not
  skipped: [ADR 0033](planning/adrs/0033-admin-console-ui-tooling-boundary.md)
  records the decision, cites the Figma File ID above, and states the three
  concrete conditions (a second reusable screen family, a second consuming
  repository, or a new component-based frontend) that make adoption the
  correct next step rather than optional.
- Repeated backend/API objects remain documented contracts and schemas.
- The current packaging decision is one standalone gateway that can be
  consumed as a module. A repository split requires a concrete independent
  consumer, release cadence, or security-provenance boundary.

**Customer next action:** approve the next exact-head PR only when its row above
has a concrete proof link, then use the next highest-priority unresolved gap to
create the following stacked change.

### Live exact-head continuation — 2026-08-25 09:40 KST

This continuation supersedes older rows for the re-listed PRs only; every
earlier snapshot row remains historical evidence for its own head. The 2026-08-25
session shipped two product changes and one scheduler change, recorded below,
and re-inventoried the whole open queue at the listed heads.

**Shipped this session (pending protected-main merge):**

- [#833](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/833)
  `fix(security): rename credential-name constants and readiness label keys…`
  root-causes the Strix B105 false-positive class: `DEFAULT_*_TOKEN_KEY`
  constants were KV credential *names*, not secrets, and `readiness_pass/warn/fail`
  were locale label keys. Renames are semantics-first (no suppression files, no
  scanner configuration change). This unblocks ~12 PRs whose diffs intersected
  `__main__.py`/`admin.py`.
- [#834](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/834)
  `feat(routing): add operator-managed model groups` implements ADR 0026:
  `ModelAgent.group_name`, measured intra-group routing
  (`P(success | Beta(1,1) data) / EWMA_latency_seconds`, Jacobson-gain 1/8, no
  arbitrary cross-metric weight), group alias resolution in
  `_requested_agent`, `/api/v1/model_groups` CRUD with agent-pool persistence,
  OpenCode Zen discovery source, zero-price/`-free` free-tier classification,
  and the admin table's measured group evidence replacing fabricated
  capacity/success percentages.
- [#835](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/835)
  `ci: hourly OpenCode maintenance agent routed through this gateway` stacks on
  #834: a `23 * * * *` UTC job copies six provider secrets into the process-local
  KV (bootstrap transport only), auto-discovers chat models, and uses the stable
  `contextual-orchestrator` gateway alias. It neither creates nor depends on a
  named model group; group membership remains operator-managed through REST/DB.

| PR | Exact head (2026-08-25 09:30 KST) | Base / mergeability | Decision |
|---:|---|---|---|
| #835 | `f21da70b7f18` | stacked on #834; UNSTABLE | `WAIT_AND_REMEDIATE` — hosted Checks + approval |
| #834 | `6b069a059b67` | main; MERGEABLE | `WAIT_AND_REMEDIATE` — hosted Checks + approval |
| #833 | `88112e49f13e` | main; MERGEABLE | `WAIT_AND_REMEDIATE` — strix rerun + approval |
| #831 | `d7efa634a1f1` | main; MERGEABLE | IDOR boundary fix; awaiting terminal Checks + approval |
| #830 | `76c18f13c2ff` | main; MERGEABLE | streaming/batch error boundary; same gate set |
| #828 | `42b6e4cb0851` | main; MERGEABLE | response-write crash fix; same gate set |
| #823 | `0a9a1932cf79` | main; MERGEABLE | LineageWeave CLI argv contract; same gate set |
| #822 | `9729ad7b85cf` | main; MERGEABLE | credential backend tests; same gate set |
| #821 | `577570ab4671` | main; MERGEABLE | token-counting tests; same gate set |
| #820 | `a185eedf7572` | main; **CONFLICTING** | rebase onto current main, then gate set |
| #819 | `5971bdcb0b68` | main; MERGEABLE | config storage tests; same gate set |
| #818 | `4cd295c2b2ab` | main; MERGEABLE | OTel session correlation; same gate set |
| #807 | `7703916f7ab1` | main; **CONFLICTING** | superseded in part by #830; rebase or close as duplicate |
| #803 | `641b2d1f078e` | main; MERGEABLE | PII purpose-limited protection per ADR 0010; gate set |
| #794 | `225271583612` | main; MERGEABLE | DB naming migration; gate set |
| #790 | `17a5e42b44f1` | main; MERGEABLE | review gateway bootstrap; gate set |
| #788 | `d5ebe735a9ee` | main; MERGEABLE | opaque admin sessions; gate set |
| #785 | `ec609fa7b526` | main; **CONFLICTING** | reasoning-effort profiles; rebase required |
| #782 | `5ab3acc5aba6` | main; MERGEABLE | workflow object authorization; gate set |
| #780 | `e4e6b7cf27f0` | main; **CONFLICTING** | liveness/readiness split; rebase required |
| #773 | `cfae080dcab9` | main; MERGEABLE | this document; self-referential row, refetch live head |
| #772 | `c038175528c8` | main; MERGEABLE | distributed response cache plus thread-isolated request sampling; gate set |
| #768 | `2a6c54636693` | main; MERGEABLE | embedding/chat isolation; gate set |
| #765 | `d19e3492192e` | main; **CONFLICTING** | paper-grounded reasoning contract; rebase required |
| #762 | `78aa5be10c58` | main; MERGEABLE | PII design ADR; merge after #803 sequencing decision |

**Gap register updates (2026-08-25):**

1. **Closed by #834:** model-group composition (per-model → per-group), measured
   speed/stability member ordering, group alias addressing, OpenCode Zen
   discovery, free-tier classification.
2. **Open — Zen pricing honesty:** OpenCode Zen `/zen/v1/models` omits prices;
   free classification currently relies on explicit `-free`/`:free` suffixes.
   Keep `unknown ≠ $0`; adopt provider-reported pricing when available.
3. **Open — quality dimension:** intra-group score is reliability×speed only.
   Cross-model quality routing must use calibrated evaluation (fast-mlsirm /
   RouteLLM-style learned router) with ablation, not hand weights (RouteLLM;
   FrugalGPT citations in ADR 0026).
4. **Open — multi-instance telemetry:** observation ledger is process-local by
   design; durable time-windowed aggregation is required before horizontal
   scaling (ADR 0026 boundary).
5. **Closed on #835 head `f21da70b7f18`: scheduler pinning and transient-model
   coupling.** OpenCode is pinned to `1.18.22`, actionlint passes, and the loop
   targets the stable gateway alias without creating an implicit model group.
6. **Open — conflicting stack:** five PRs (#820, #807, #785, #780, #765) need
   rebases before their gate sets can complete; #807 may be closed as
   functionally superseded by #830 if review confirms full coverage overlap.

**Customer next action:** merge order is #833 → #834 → #835 (stack), then work
the table top-down; each row needs terminal Checks plus independent approval on
its exact head before a normal protected merge.

### Capability-group exact-head continuation — 2026-08-25 10:42 KST

This continuation supersedes the preceding model-group/scheduler rows. Model
identifiers used during design were transient examples and are absent from the
contract: equivalence is an operator assertion, never a name-derived inference.

| PR | Exact identity and live boundary |
|---|---|
| [#834](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/834) | head `fae8665771443587fcb64bc517a005412c979c14`, base `50014ef9f87623c6dfd529116297c5d180743125`; open, auto-merge enabled, `REVIEW_REQUIRED`, replacement Checks pending. Its tree `017ca560293c7939b405af6fa25c7f0e3ba13e76` is identical to the locally validating #838 tree. The preceding capability tree passed `1605` tests before parent integration plus `66` focused post-merge tests; #838 adds `28` focused DB/Admin/group tests, with the full exact-tree run still in progress. No protected-main claim is made until exact-head hosted gates and independent approval finish. |
| [#837](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/837) | head `b2d7aea0d71b5669d6c0167527691592a9ab2abe`; normally merged into #834's feature branch at 2026-08-25 10:30 KST. Adds provider-declared `text`, `image`, `video`, `speech`, `transcription`, `embedding`, `rerank`, and `audio` discovery/routing surfaces; its merge-result tree equals #834's current tree. This is stack integration, not protected-main release evidence. |
| [#835](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/835) | head `f21da70b7f184b687b9c4996327c18d384c420d0`; normally merged into #834's feature branch at 2026-08-25 09:52 KST. The hourly loop uses the stable gateway alias, a random loopback bearer token, job-scoped write permission, hash-locked Python requirements, and lockfile-integrity-checked OpenCode `1.18.22`. |
| [#838](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/838) | head `2de42512ac552246b8a5bc024ba179b3addcc1ed`; normally merged into #834's feature branch at 2026-08-25 10:39 KST. It migrates group membership from duplicated agent JSON into 3NF `model_group`/`model_group_member` relations and adds an accessible Admin REST editor plus capability coverage. Its merge-result tree equals #834's current tree; this is stack integration, not protected-main release evidence. |
| [#772](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/772) | head `33bd77ed216f274d658e288c05d9dca6018e07b5`; open/blocked, no failed hosted check at refresh, three pending/external contexts. |
| [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768) | head `2bb7538c614e9bd8686ba9007c2955b6c770390d`; open/blocked with stale `CHANGES_REQUESTED`, one failed and three pending/external contexts. Exact failure and unresolved review evidence must be remediated before merge. |
| [#803](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/803) | head `6b6bd783272033d7de93d584b7618b4445b5f391`; open/blocked with one failed and three pending/external contexts. The earlier PII and hash-lock local evidence does not clear the current hosted failure. |
| [.github#1316](https://github.com/ContextualWisdomLab/.github/pull/1316) | head `c169b146cfaaebd2ba75ee781bfcf1d82f4dbb84`; central repair aligns Strix's required-workflow smoke contract with its current direct-OpenAI fallback. Auto-merge is enabled; hosted gates remain mixed/pending. Until it normally merges, target-repository Strix failures showing the retired fallback assertion are central-contract failures, not source security evidence. |

Research boundary: MMR-Bench supports modality-aware routing evaluation, while
Jacobson EWMA and the Beta-Bernoulli posterior support the measured latency and
stability estimators. None of those sources proves that two provider identifiers
represent one model; only operator/provider provenance can establish group
membership. The successful-responses-per-second quotient remains a transparent
product policy, not a reproduced paper result.

Buyer-visible gaps now prioritized:

1. Video submission is routed, but provider-affine polling/content download and
   durable job ownership are not yet represented; add a normalized async job
   resource before calling video orchestration production-complete.
2. **Closed on the #838 stack:** Admin exposes group capability coverage and a
   keyboard/native-form REST editor; DB membership is normalized and legacy JSON
   membership migrates without data loss. Authenticated deployed-browser runtime
   evidence remains a release/UAT gate rather than an implementation gap.
3. Free-model tests are deterministic catalog-contract tests. Add an opt-in,
   spend-capped live OpenRouter canary selected from current zero-price metadata;
   never pin a transient free model identifier in production or CI.
4. Multi-instance routing observations remain process-local. Add a time-windowed
   durable observation model with calibrated decay before horizontal scaling.
5. Protected main, not a feature-stack merge, remains the release boundary; do
   not bump or publish a version until #834 has exact terminal gates and an
   independent current-head approval.

### Capability routing contract remediation — 2026-08-25 10:46 KST

[#839](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/839)
head `852fc1eeb2f30f212694702fe96afba216eddee9` normally merged into #834's
feature branch. The resulting #834 exact head is
`19ab869094a8b877fe70397ff6de55c357654efe`, tree
`c92e2c90a14d9e8f296c536cb0172da92eaa35b6`; auto-merge is enabled, but it is
still blocked on replacement hosted Checks and independent review. The patch
closes three exact review findings: unavailable capability pools now honor the
documented 503 contract, unknown explicit model/group names return 400, explicit
groups retain true streaming in auto mode, and top-N discovery honors
provider-reported prices before price-book refresh. The focused regression set
passed 41 tests; the full exact-tree suite is running. This stack merge remains
non-release evidence until protected `main` contains the tree.

PR #773 is currently `ebf397e03c6c69a214a015c39efade6f78c603e1`, with
auto-merge enabled, several successful security/review contexts, and remaining
full-suite/fuzz/security contexts in progress or queued; `REVIEW_REQUIRED`
therefore remains the honest decision boundary.

[#841](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/841)
head `c4896ae4d1d410fdd933b8ae9e99a870d1d2cc9d` subsequently merged normally
into the #834 stack, advancing #834 to exact head
`4bf5cf0a8dce43d7a08a8e9f6ed79bb00017cb03`, tree
`549e85b33dc9cc2941d3983b397add60415b66d0`. It prevents a provider's JSON-null
modality arrays from aborting cross-provider discovery; the focused discovery
suite passed 23 tests. The immediately preceding tree passed the complete local
suite (`1611 passed in 645.34s`); because #841 changes that tree, the current
head still requires its replacement exact-head hosted full-suite result.

Two adjacent queue failures were also remediated at their own heads: #768 is
now `4d3d11ec2836e21b973ab7573322ac883abfb785` and preserves explicitly declared
non-chat capabilities through discovery/agent creation (38 focused tests); #803
is now `030b4348eb4ecdf85d1017f8891cac9faa5a0394` and restores the exact CPython
3.12 Atheris lock marker (1 focused test). Both have normal auto-merge enabled
and remain gated by fresh hosted Checks/review; neither is merged evidence.

### Product/technical specification trace — 2026-08-25 11:02 KST

[#842](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/842)
head `49d0940e04a680648743d9890f79c7110167e820` normally merged into the #834
feature stack, advancing #834 to exact head
`4e0cbca934e7e82cbed56de347853dbc40971f20`. The new
`docs/model-group-product-technical-spec.md` derives the PRD, user stories,
acceptance criteria, TRD, normalized persistence model, REST status contract,
flow/class UML, security/operability boundary, and Admin UI audit from ADR 0026
and the implemented surfaces. Its focused paper/API/DB/group/capability contract
set passed 39 tests. Current-head review threads are zero; replacement hosted
Checks and independent approval remain required.

Research was re-verified against the primary arXiv records for MMR-Bench and
RouteLLM and current official OpenRouter/OpenCode documentation. The exact
boundary remains: research supports modality-aware and learned cost/quality
routing, but does not establish provider-alias identity. OpenCode's own mutable
catalog currently demonstrates why transient free model identifiers must stay
out of the production contract.

### Release-candidate exact tree — 2026-08-25 11:18 KST

[#840](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/840)
was reordered as a stack prerequisite instead of an independently mergeable
main release: feature head `4e0cbca934e7e82cbed56de347853dbc40971f20`
was merged into release head `fd6dde7e8f06a1d3b67400355f6223c2a653aa3d`,
the PR base was changed to #834's feature branch, and its resulting three-file
diff (`CHANGELOG.md`, `pyproject.toml`, `uv.lock`) normally merged. This removes
the risk of publishing version `0.2.0` before its implementation. It also
restores the pre-existing tool-fallback changelog entries and synchronizes the
lockfile package version.

#834 is now exact head `6f494131774f38b78bdc3b104451e2133edb5318`,
tree `52fdbdcb96bbe0a7617a4573e9c01cd5355db350`. That exact release-candidate
tree passed the complete local suite (`1612 passed in 724.94s`) and produced
both the `0.2.0` sdist and wheel. Protected-main publication remains unproven:
hosted jobs are queued, independent review is required, and no tag or package
has been published.

The shared Strix contract repair is
[.github#1316](https://github.com/ContextualWisdomLab/.github/pull/1316) exact
head `e4f9865a1b06978324f006ee3861b84953877d8b`; its sole informational review
thread was resolved and auto-merge is enabled, while central hosted gates remain
queued. Until that protected merge lands, the queue-wide retired-smoke Strix
failures remain central workflow evidence rather than individual source defects.

### Adjacent PR remediation loop — 2026-08-25 11:31 KST

The protected queue advanced without bypasses; every row below has auto-merge
enabled and remains open until its fresh exact-head gates complete:

| PR | Exact head | Remediation evidence |
|---:|---|---|
| #831 | `634fe03576d986794b121e0da05179f1663073f4` | Wrong-pool POST now matches GET/PATCH/DELETE with 404 `agent_not_found`; 8 focused tests passed. |
| #830 | `d727c0897e94568539c22af19d88e055b88aaa56` | Current main merged; three remaining review notes verified as intentional provider-error boundary behavior and resolved. |
| #828 | `bde1975c8c6e843b6339c6b7f3922dad1b0f07c5` | SSE disconnect now stops upstream token work and releases the run slot; 15 focused tests passed. |
| #794 | `6efeacae06d7445d71991cb7faf970b5a3a1ab65` | SQLite SAVEPOINT preserves caller-owned transactions; direct test-file execution and 28 pytest cases passed. |
| #788 | `1fc1ddc24ef8b0c5009c9212efb803a79d0deaef` | Opaque admin sessions now authorize evaluation runs, erase failed bearer input, and avoid duplicate readiness fan-out; 27 focused tests passed. |

These are PR-head claims only. None is protected-main or release evidence until
terminal Checks and required independent approvals cause a normal merge.

### Live exact-head continuation — 2026-08-27 09:28 KST

Added model capability prior integration for `ModelGroupRouter`:
- Embedded `Chatbot Arena` and `Artificial Analysis` baseline scores as Beta distribution priors.
- Updated `ModelGroupRouter` to accept a `prior_resolver` without breaking the existing group stability calculation or `_report_locked` structure.
- Updated `contextual_orchestrator/orchestrator.py` to use `resolve_quality_prior` for its `_quality_router`.
- PR #883 requires investigation for `strix` check failures.
- PR #888 and #887 have their CodeRabbit comments handled or under review.
- The 1-hour recurring `schedule` gap-loop continues.

### Live exact-head continuation — 2026-08-27 09:52 KST

Added OpenRouter upstream real-time reliability collector (`OpenRouterUptimeCollector`):
- Fetches live telemetry (`uptime_last_30m`) from `/api/v1/models/{model_id}/endpoints`.
- Dynamically integrates this telemetry into `ModelGroupRouter` by exposing `update_prior` to safely adjust `alpha` and `beta` values without mutating underlying stability logic.
- Avoids HTTP blocks during startup by orchestrating a non-blocking Daemon thread polling at set intervals, enabling resilient routing dynamically over time.
- Integrated the change into PR #892 (`feat/model-capability-priors`) and pushed to the origin repository.

### Live exact-head continuation — 2026-08-27 12:0x KST (arbitrary-weight remediation)

GAP RESOLVED on PR #892 head `af9d667f…+fixups`:
- The shipped `_BASELINE_PRIORS` table carried invented Beta pseudo-counts
  ("alpha=10, beta=1…" style), violating the organization rule that no
  weight may be arbitrary. Replaced with a measurement-typed derivation:
  published Arena Elo and Artificial Analysis Quality Index are normalized
  by each instrument's own median/MAD, averaged, squashed through the
  logistic, and split across exactly the repository's existing Laplace
  evidence budget (`PRIOR_EVIDENCE_BUDGET = BETA_PRIOR_SUCCESS_COUNT +
  BETA_PRIOR_FAILURE_COUNT`). Mass is conserved: measured members never
  receive more evidence than unmeasured ones. Unknown identifiers keep
  the unchanged Laplace pair.
- The uptime collector's invented `weight = 50.0` penalty was removed.
  Each poll now folds one window of provider-measured availability into
  equivalent Bernoulli mass (`successes += u/100`, failures`), so all
  counts trace to polls; failure denominator = polls performed.
- `ModelGroupRouter.update_prior()` was added so prior components can be
  refreshed atomically while `success_count`/`failure_count` remain
  bit-identical — telemetry can no longer masquerade as outcomes.
- Collector previously called the nonexistent `update_prior`; it now has
  a contract + tests, hardened HTTPS/percent-encoded fetch, full
  docstrings, and injectable startup delay for deterministic tests.
REMAINING GAP (follow-up loop): re-fit these priors against fast-mlsirm/
TEPP calibrated quality latents before enabling benchmark priors on any
revenue-serving route; until then their influence is capped at the same
budget an unmeasured member already spends.

### GAP RESOLVED (partial) — 2026-08-30 20:57 KST: `stream_options.include_usage` + `tools` gateway rejection

**Symptom**: every Strix scan org-wide against `orchestrator/free` failed closed with
`400 invalid_stream_options` (evidence: `.github` run `33307905354`, job
`99247611184`, step 23). Strix's `openai-agents` SDK always sends
`stream_options.include_usage=true` alongside `tools` on every streamed turn
(`strix/core/inputs.py::make_model_settings`, no supported opt-out that keeps
streaming), and `server.py`'s tools/response_format passthrough branch rejected
that exact combination unconditionally, before any upstream call.

**Root cause was gateway-side, not a real upstream constraint.** No provider
(OpenAI, NVIDIA NIM, OpenRouter, Bytez) rejects this combination — this
codebase has never sent `tools` + `stream=true` to a real provider in the
first place; `proxy_completion()` always forces `upstream["stream"] = False`
for tool-calling requests. `_chat_response_sse_chunks` (the SSE framing
function this passthrough already calls) had independently tested tool_calls
delta framing. ADR 0006 subsequently removed its estimated-usage fallback:
valid provider usage is reported and missing usage is explicitly unavailable.

**Fix**: [PR #925](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/925)
narrowed the rejection from *all* `tools`/`response_format` structured
passthrough to `response_format`-only (conduct mode, no tools).

**Why not remove the rejection entirely** (a competing, independently-authored
fix, PR #924, took that broader approach and was closed in favor of #925):
traced `cost_router.py:456-507` — a conduct-mode multi-step workflow's
`result["usage"]` dict is built by summing per-step counts and is *always*
populated, but carries no `usage_source`/`measurement_status` tag of its own;
when a step's provider response omitted usage, the historical sum silently
included a local token-count estimate.
`_chat_response_sse_chunks` labels any populated `usage` dict
`"usage_source": "reported"` unconditionally — it does not check
`payload["cost"]["measurement_status"]`, unlike the sibling
`orchestrator.py::chat_completion_chunks` (used by the *other* conduct-mode
streaming path), which already correctly gates usage emission on
`cost.get("measurement_status") == "measured"`. Removing the rejection for
`response_format`-only would have let the gateway present a gateway-side
token estimate as `"reported"` for a live SSE consumer — precisely the kind
of fabricated-precision the project's Honest metrics convention exists to
prevent. `tools` passthrough doesn't have this exposure (always one
non-streaming upstream call; `payload["usage"]` there is always the raw
provider JSON's own field), which is also exactly the shape Strix needs.
**Resolved by the conduct SSE usage follow-up**: `_chat_response_sse_chunks`
now applies the same `measurement_status == "measured"` gate
`chat_completion_chunks` already has, so conduct-mode streamed usage is exposed
only when measured instead of rejecting the whole streaming request.

**Follow-up delivered by ADR 0006**: `_chat_response_sse_chunks` now emits
measured usage only for valid provider counts and otherwise emits null usage
with an unavailable status rather than synthesizing the historical estimate.

**Duplicate-work consolidation** (concurrent autonomous sessions independently
converged on the same bug): closed contextual-orchestrator#924 (superseded by
#925, evidence above); closed `.github`#1445 (duplicate of #1442, orphaned
direct-NVIDIA-NIM resolver removal — unrelated cleanup, same root discovery
day); closed `.github`#1447 (duplicate of #1448, both temporary
`LLM_DISABLE_STREAMING` mitigations for Strix — #1448 is correctly scoped to
only the contextual-orchestrator loopback base URL, #1447 was unconditional
and would have also disabled streaming on Strix's other provider fallbacks).
`.github`#1448 is held open, unmerged, as a fallback only: the correct fix is
root-cause (#925, in normal — not bypassed — review, since it does not touch
`.github`'s trusted scripts), and a non-streaming workaround is technical debt
that would need a follow-up revert. Will bypass-merge #1448 only if #925's
review stalls well beyond this org's accepted multi-hour LLM-review latency.

**Follow-up (2026-08-30, same head): Devin review finding on #925, CONFIRMED
and fixed.** The `tools`-passthrough narrowing above assumed the one
upstream call "always" carries provider-reported usage. Traced
`ModelClient.proxy_send`/`_proxy_send` (`orchestrator.py`): it returns a
provider's raw JSON verbatim and neither requires nor synthesizes a `usage`
key, so a real provider omitting it was untested and unproven safe. Added
`tests/test_stream_options_null_flags_noop_http_honesty.py::test_http_chat_tools_streams_estimated_usage_when_provider_omits_it`,
a real (loopback `local://`) HTTP provider — `mock://` agents cannot exercise
this, since `ModelClient._mock_raw` always injects a zero-valued `usage`
dict — whose tool-call response omits `usage` entirely; confirmed the
existing `_chat_response_sse_chunks` fallback (already used for the
non-tools case) correctly labels the resulting chunk `usage_source:
"estimated"`, never `"reported"` (RED-before-GREEN: flipping that one label
in `server.py` makes this new test fail). No behavior change was needed —
this closes the coverage gap and corrects the PR's own comment/README/
CHANGELOG language, which had overclaimed the guarantee.

**TRACKED FOLLOW-UP (2026-08-30, action required once this PR merges):**
a concurrent session merged `.github#1448`
(`LLM_DISABLE_STREAMING=true` for Strix against the contextual-orchestrator
loopback) at 12:15 UTC, before this PR merged. Its own justification is a
*separate*, real deadlock, not a disagreement with the analysis above:
`pr_review_merge_scheduler.py::inspect_pr` requires completed Strix
evidence on a PR's head before it will ever dispatch OpenCode review, so a
PR fixing Strix's only failure mode could never itself pass the review
gated behind Strix succeeding — a genuine self-referential deadlock,
independent of the `stream_options`/`tools` root cause this PR fixes.
Confirmed with the user this is explicitly a temporary workaround, not the
resolution: it trades away Strix's real-time SSE streaming to route around
the gateway bug rather than fixing it. **Once this PR (#925) merges**,
Strix's `tools` + `stream_options.include_usage=true` requests will
succeed on their own against `orchestrator/free`, and the
`LLM_DISABLE_STREAMING` opt-in in `scripts/ci/strix_quick_gate.sh`
(`.github`) becomes unnecessary technical debt — file a follow-up PR in
`.github` to revert it and restore real SSE streaming for Strix scans.
Do not let this workaround become permanent by omission.

**CONFIRMED (2026-08-30, ~21:52 KST): `.github#1451`'s narrower-scope claim
proven correct, with a real posted verdict as evidence.** Earlier today
`.github#1451`'s own PR body/comments overclaimed "blocking every PR
org-wide" for the `pingora_edge_policy.py:345` coverage gap; corrected in
that PR's comments once verified. The precise mechanism:
`opencode-review-dispatch.yml`'s `coverage-evidence` job measures the
*target PR's own repository's* coverage (it clones and tests whichever
repo the reviewed PR lives in) — for a `.github`-hosted PR that happens to
equal `.github`'s own `scripts/ci`, so the fix only unblocks `.github`
PRs specifically. Confirmed by contrast: `fast-mlsirm#1473`'s post-merge
dispatch (run `33311678659`) still failed `coverage-evidence`, but for a
completely unrelated reason native to that repo (a Rust extension import
error, `cannot import name '_core' from partially initialized module
'fast_mlsirm'`, plus 69.8% docstring coverage) — proving the fix's scope
boundary directly rather than assuming it.

**End-to-end proof the `.github` scope now works**: `.github#1452`'s
dispatch (run `33312352417`) is the first all the way through today:
`coverage-evidence` succeeded, `Run OpenCode PR Review model pool`
succeeded, and `opencode-agent[bot]` posted a real, substantive,
evidence-based review on the current head — `CHANGES_REQUESTED` citing
that PR's own unrelated failing checks (`osv-scan`, cancelled `Strix`),
plus a genuine Changed-File Evidence Map covering the actual diff. Not a
rubber stamp, not a coverage-gate skip: the review mechanism itself is
now demonstrably working for `.github`-hosted PRs. Minor unresolved
detail on that same run: "Publish repository_dispatch OpenCode status"
failed after the verdict was already correctly published and enforced —
a downstream status-publish step, not the review pipeline itself; not yet
investigated.

**Superseded timeout diagnosis** (traced via `.github#1276`'s
`noema-review` run, flagged by the user as "still not working" after the
above fixes landed): `TaskOrchestrator._invoke()`
(`contextual_orchestrator/orchestrator.py:6353-6537`, the per-agent
call/retry/failover loop) could run longer than the sidecar's former
120-second client ceiling. That did not prove an internal hang; it proved
the outer limit could terminate a healthy slow model. The former proposal
to add an overall `_invoke` deadline is withdrawn. PR #971 removes fixed
wall-clock limits from inference, discovery, OpenRouter ZDR lookup, and
local readiness paths; only operator cancellation or a superseded PR head
may terminate that work.

**Correction (2026-09-03): the "overall deadline on `_invoke`'s
candidate/retry loop" recommendation directly above is STALE and
contradicts binding org policy — do not implement it as written.**
`docs/product-goal-directive.md` section 8 is this org's binding
no-fixed-inference-cap policy (no common timeout ceiling across the
application/agent/gateway stack; the default stays null/unbounded, and a
real communication failure is left to end via the upstream provider's own
timeout or error, not an artificial cutoff). This policy already produced a
concrete precedent since this entry was written:
`docs/doctoring/autofix-and-noema-review-model-job-timeout-removal.md`
reverted job-level timeouts added around two other synchronous model calls
for exactly this reason. An overall wall-clock deadline on the
candidate/retry loop, as recommended above, is exactly such a fixed
inference-time cap and must not be added on this entry's authority alone.
A follow-up investigation (`.github#1804`, root-causing the same `_invoke`
serial-failover mechanism via four cross-repo stalls measured at
649.5s/1332.6s/1462.9s/2161.9s) found the correct fix direction requires
either (a) a separate, not-yet-built durable candidate-exclusion/skip
mechanism that consumes the still-unmerged `contextual-orchestrator#911`'s
EWMA-based candidate-ranking observation data once #911 lands — #911
itself only reorders candidates by an EWMA score and does not add
exclusion/skip logic, so landing #911 alone would not let a known-failing
candidate be skipped — or (b) a documented, owner-approved policy
exception if deliberately racing non-equivalent endpoints is ever
authorized. Neither is done as of this correction, and (b) is constrained
by this org's `endpoint_equivalence` racing invariant
(`docs/doctoring/equivalent-endpoint-racing.md`; this repo's own
`CLAUDE.md` header: "Equivalent model-group endpoints may race only
through the normalized, explicit endpoint-equivalence contract") — racing
genuinely different, non-equivalent models to dodge a slow candidate would
itself be an undocumented production routing/quality change, not a safe
default. The measured stall durations and root cause recorded above remain
accurate; only the "add a deadline" recommendation is superseded.

**Amendment (2026-09-06): option (a) above is missing a second half, and
the existing circuit breaker is not the exclusion mechanism it looks
like.** Read at pin `414f2297`, `TaskOrchestrator` already carries a
per-agent breaker — `_record_failure` (`contextual_orchestrator/orchestrator.py:8048`)
counts failures and opens at `circuit_failure_threshold = 3`, and
`_circuit_open` (`:8031`) gates admission. Two measured properties stop it
from excluding a stalled candidate:

1. **The tool-bearing passthrough path never reaches it.** Noema's
   no-tools `_invoke` route-walk recorded timeouts as `circuit_failure`
   and failed over (9 of 14 and 10 of 15 in two samples), while Strix's
   passthrough recorded **0 of 21, 0 of 48, 0 of 63 and 0 of 65** across
   four samples. A bare `TimeoutError` is re-raised as a
   `500 internal_error` before `_record_failure` runs, so the breaker
   never sees the failure it exists to count. That is exactly the scope
   of the still-open `#1082`.
2. **`circuit_reset_seconds = 30.0` is short relative to one stalled
   attempt.** `_circuit_open` sets `state["failures"] = 0.0` once
   `circuit_reset_seconds` have elapsed since `opened_at` (`:8036-8038`),
   so the counter is cleared, not merely the open flag. Against the ~90 s
   attempts these stalls actually take, a route is re-admitted after 30 s
   and needs three fresh failures — up to another ~270 s of wall clock —
   to be excluded again. The breaker suppresses roughly a tenth of the
   time spent on a known-bad route; it does not skip it.

So landing `#1082` is necessary but not sufficient for option (a): it
makes the failures countable, and a durable exclusion still needs a reset
policy scaled to the observed attempt duration rather than a fixed 30 s.
**Third gap, found the same day and the strongest of the three: a single
success erases the count.** `_record_success`
(`contextual_orchestrator/orchestrator.py:8073-8077` at the same pin) does not
decrement the failure counter — it pops the agent's circuit state outright:

```python
def _record_success(self, agent_id: str) -> None:
    with self._circuit_lock:
        cleared = self._circuit.pop(agent_id, None)
```

With `circuit_failure_threshold = 3`, any one success therefore zeroes the
accumulated count. A route that alternates failure and success — which is what
an overloaded provider does — never reaches three and is never excluded at all,
regardless of how much wall clock each failure burns. Reproduced three times on
2026-09-06 across three separate pull requests, each on the single ready route
the post-`.github#1957` preflight had found:

| PR | failure | `circuit_cleared` | failure again, from zero |
|---|---|---|---|
| this PR (`#1043`) | 16:07:49.665 | 16:07:57.361 | 16:08:46.896 |
| `.github#1938` | 17:59:55.035 | 18:00:36.785 | 18:01:55.884 |
| `.github#1913` | (same sequence) | | |

Three runs, one mechanism: this is a property of the breaker, not a reading of
one log.

`#911` remains unmerged as of this amendment (verified 2026-09-06), and it is
further from merged than "unmerged" suggests: its base is not `main` but
`codex/nim-evidence-successor`, which is itself `#1068` (open), based in turn on
`codex/stacked-security-successor`. "Once `#911` lands" therefore requires that
whole stack to land first.

None of this changes the conclusion above — a fixed wall-clock deadline on the
candidate/retry loop is still barred by section 8 — it only records that the
"not-yet-built" mechanism has **three** independent missing pieces, not one.

**No-heuristics boundary (2026-09-07): these observations are diagnostics, not
automatic exclusion authority.** Neither #911's EWMA observations nor an
observed-attempt-duration scale identifies a reset, failure count, window,
weight, or admission decision. Until the canonical routing owner supplies an
executable mathematical/statistical availability model, an identified
loss/utility and preregistered validation design with uncertainty, or an
authoritative standard governing this exact path, automatic candidate
exclusion remains unset and must fail closed or use an explicit
operator-supplied decision. Do not replace 3/30 seconds with different
repository-authored values. #1000 owns the broad routing repair; #911's
observations can remain evidence but are not by themselves a production
policy.

## 2026-09-12 Optimizer cardinality acceptance and calibration boundary

Frozen `090b4ec841cfc78b45248b561f1cef6396b57429` rejects incomplete/extra
custom batch outputs before callbacks, preserving incurred usage. Corrected
route-mode RED has six actual batch failures; full source **3,791 passed,
2 skipped**, separate installed core **222 passed**. Earlier fixture failures
are corrected, not counted as product reproductions. Exact commands, hashes
and failed attempts are in [the recovery runbook](doctoring/optimizer_score_recovery.md).
The PR remains Draft: this repair does not supply calibrated production
ranking or observed accuracy/latency gains. Reuse fast-mlsirm's existing
validation-profile owner successor #1737 rather than create a parallel consumer
manifest; it is not in the inspected v0.9.1 release.

The historical overall-deadline recommendation above is not current policy:
model timeouts default to null, and a terminal 502 alone does not justify a
new application-wide timeout or caller-side provider fallback. Trace the
actual eligible candidates and request phases before changing owner behavior.

Production approval boundary audit at `d43e08c7`: generic optimizer callback
scores and recommendations are not calibration approval. No production
approval adapter was identified in this checkout's runtime call graph; external
callers remain outside that audit. Preserve descriptive/checkable-answer APIs
and do not invent a purpose/profile layer in this repair. The canonical owner
follow-up must define released applicable evidence, verification and lifecycle
checks, and fail-closed production recommendation tests before an actual
production caller adopts it. See the
[adapter audit](doctoring/optimizer_score_recovery.md#production-approval-adapter-audit--2026-09-12).
This gap remains open independently of the repaired cardinality/usage defects.

### HTTP resource lifecycle follow-up — local candidate, 2026-09-12

Owner: CO transport, stacked on #1135 exact
`c7ed39397bd8771b44250a61ab0ee8818889152a`; test cleanup is inherited as
`87dcc53fb868bfa615c27c42fdc73aa69c4f1875`. Customer outcome sought: release failed
stream resources while preserving the actionable error, terminal tool stop and
response-size limit. No routing score or model timeout changes are included.

The HTTP 500 cleanup defect was reproduced before repair. The local candidate
closes its error response after classification; closer failures cannot replace
the safe primary error. Three affected test files passed 56 cases with warnings
as errors. Expanded parent/successor suites remain nonclean. All 25 observed
failure nodes were run independently on both trees: 50 processes had matching
per-node exits and core warning/error signatures (addresses/ephemeral ports
excluded). This bounds the observed order-dependent baseline limitation; it
does not relabel the suite as GREEN. Full-suite, hosted review,
protected merge, deployment, real accuracy and latency gains remain unverified.
See [the lifecycle runbook](doctoring/http_test_resource_lifecycle.md) for RED
receipts, the rejected unsafe closer behavior, parent lineage and remaining gates.

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

## 2026-09-27 PR #1269 executable-fixture carryover — Proposed

Canonical successor PR #1266 already contains predecessor #1269's two
production repairs: `ProviderEmbeddingBatchBackend.wait(timeout=None)` keeps
the no-implicit-deadline contract, and EgressWeave allowlist misses remain typed,
non-retryable `provider_connection_error` 502 responses. Existing successor
tests cover direct unbounded completion, infinite waits, coordinator defaults,
and allowlist classification/failover.

The remaining distinct executable requirements are carried at
`2eceb6474c2904ae308991e89595b1f44c852940`: a finite wait returns while the
provider is blocked, and the real default `/v1/embeddings` HTTP route forwards
`ModelClient.timeout=None` unchanged to the provider backend. The predecessor's
exact `cd30956feda8452aedb751a30a7f0206c442e1b2` reported 8/8 focused GREEN;
the successor's isolated finite-deadline case passes and its exact test blob
`8db8c9ec80757d25cd715aa3acaf191c7f613640` compiles. Fresh exact-head hosted
execution and independent approval remain required; status stays Proposed.

## 2026-09-27 Same-agent selection receipt fidelity — Proposed

PR #1266's deterministic selection receipt recorded each candidate once even
when the research-backed retry decision made multiple real calls to the same
Agent. That understated request execution and contradicted the existing
endpoint-race invariant that `attempted_deployment_ids` reproduces actual call
order and multiplicity. RED `f56e10d3` extends the ordinary free-pool retry
fixture: five real provider calls produced only three receipt entries. GREEN
`9188e232` appends the deployment identity inside the retry loop, preserving
each call without changing retry admission, ordering, weights, or fallback.
Exact-head hosted execution, independent approval, protected-main integration,
and immutable release remain required; status stays Proposed.
