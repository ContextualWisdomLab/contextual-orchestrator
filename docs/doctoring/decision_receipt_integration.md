# Initial decision receipt integration candidate

Status: incomplete implementation for issue #1110; not release evidence.

## Supported entrypoint repair, 2026-09-12

Parent: `de21ffd42733d6115800b33c4e84b3626a33f758` (#1107).
The supported call chain is CLI `main` → `serve` → `build_server`.
Only the builder accepted `decision_receipts`, so ordinary server startup could
not enable the existing measurements. The successor adds a keyword-only,
default-false forwarding option to `serve` and one explicit CLI switch,
`--decision-receipts`, beside `--serve`. The native implementation and durable
store checks remain in the existing builder; no estimator or timer is copied.

The 2026-09-12 ownership inventory contains **91 open PRs**, correcting the
earlier 90-PR snapshot. Sixteen touch either entrypoint file. Fresh GraphQL head
identities and local exact-object merge-base diffs showed no changes to `serve`
or its CLI invocation. This is a hunk audit, not whole-stack merge acceptance.
#911 inserts a routing-observation option after `--state-db`; preserve that
adjacent delta. #971 changes discovery-command help, not this parser option.
#1107 owns the builder receipt hooks; #1138 changes export routing separately.

| PR | Audited exact head |
| --- | --- |
| 1138 | `8de04219e2ce58c6f88504d8cb6c7f41056293cd` |
| 1130 | `440847c3a4a2d698c6f6d1b92848d2d4743b5337` |
| 1107 | `de21ffd42733d6115800b33c4e84b3626a33f758` |
| 1074 | `2157d702c4609cc51829d7423911cadf26cf83d0` |
| 1053 | `76c047585f54fcbe940fe168412f51627d3f79dd` |
| 1037 | `4ba6be741bdee62bc4b1b3ae498e8d3415f4653c` |
| 1022 | `35a518be78a375bb9e2821bcbb5c1b9ed713e155` |
| 1021 | `61d5170b96a3e579ebe1aa237d0c55b67246e72c` |
| 1017 | `e84d39c2c25f4ebae67247888d8e892f928e820d` |
| 983 | `53aa9c5c7fcbb6a0dc573e22c67e3ef9e8f9474d` |
| 982 | `20783edd7b39ff6439e9ea463f17d2e274b0ade8` |
| 978 | `200135d07ab3e30bc00a1ab1a8f314a87fa5b547` |
| 977 | `845f5c5dc146e5dc1515a451a6c51fc12ed70cc2` |
| 972 | `876f1679cd44d7e9691b95344118bfe324e31287` |
| 971 | `d9c2f57701f6e7fe194582b510255759ffb30990` |
| 911 | `e80949188f0afa86052f10f5a9b627da1ee1ef0b` |

Reproduction uses the existing project-local Python 3.14 environment at
`/Users/seonghobae/Documents/ChatGPT/contextual-orchestrator/.venv/bin/python`
from the successor worktree. No dependencies were installed. An initial attempt
at a worktree-local `.venv` failed because that environment does not exist.
Run `python -m pytest tests/test_decision_receipt_entrypoint.py -q -W error`
with that interpreter: before source changes, four failures in 1.80 s exposed
missing forwarding and the unrecognized flag; afterward four passed in 0.29 s.
These are entrypoint unit checks, not installed-artifact or real-request proof.

The related CLI auth/logging/role-effort and telemetry suites with `-W error`
returned 104 passed and two failures in 5.69 s including the four new cases.
The unchanged parent returned 100 passed and the same two failures in 5.20 s:
`test_traced_recognizes_litellm_prefixed_json_object_diagnostic` and
`test_traced_does_not_export_classified_provider_prose`, both HTTPError resource
cleanup warnings. The candidate additionally emitted a cleanup warning during
shutdown. Do not describe this as a clean full suite or suppress the warnings.
Resource ownership needs its existing owner-stack repair and revalidation.

Isolated follow-up distinguishes shutdown timing from a new leak: the unchanged
parent running only those two telemetry nodes reported two passed in 1.04 s but
exited 1 during `pytest_unconfigure` with the same `HTTPError 400: 'bad'`
implicit-cleanup warning. The new six entrypoint tests plus existing CLI suites
passed 58 cases in 2.53 s with `-W error` and exit 0. A candidate expanded rerun
with allocation tracing reported 106 passed and the same two failures in 25.41 s,
plus the shutdown warning. Therefore the shutdown symptom is parent-reproducible,
not evidence of a candidate-only listener leak. The allocation follow-up below
narrows ownership. No warning filter or unrelated teardown was added.

Allocation follow-up on the unchanged parent identified the test-owned
`urllib.error.HTTPError` construction at `tests/test_telemetry.py:1223` inside
`test_traced_recognizes_litellm_prefixed_json_object_diagnostic`; no entrypoint
test was loaded. The same shutdown signature followed two passing nodes (1.05 s,
process exit 1). This baseline defect is not repaired in this successor.

Offline packaging used `uv build --wheel --offline` with the existing Python
interpreter and cached isolated build backend. The non-isolated attempt lacked
setuptools, and the project interpreter has no pip; neither was installed into
the shared environment. The resulting core wheel SHA-256 is
`a51ce8658a723691a9d02accb03645ff9704dbe62ba326e0240028b96be193bf`.
A fresh isolated environment installed this wheel and cached dependencies
offline. Outside the checkout, `python -I -m pytest` with `--noconftest`
and `--import-mode=importlib` passed all six entrypoint tests in 3.19 s.
Core and server import origins were under that environment's site-packages.
The CLI test uses an explicit agent fixture path to avoid depending on the
working directory. This verifies the uncommitted core source candidate, not
native-wheel integration, final-commit packaging, or a released artifact.

The analytics export remains bounded to 256 retained admissions with
`measurement_complete=false` and `reconciliation_required=true`. Complete ingress
reconciliation and independently adjudicated outcomes are still required.
Enabling this option alone cannot prove an accuracy or latency KPI improvement.
Independent diff review found no runtime defect but requested missing-native and
missing-store startup checks. Both now exercise `serve` and verify no listener
is created; the native module is replaced only within these unit tests. The six
focused cases passed in 0.31 s with `-W error`. Local browser inspection at
1265 × 712, English, covered this added section and ownership table plus the
changed AGENTS, CLAUDE and Gap paragraphs. Directly viewed overlapping captures
showed readable wrapping without overlap or clipping. This is changed-section
desktop inspection, not whole-product or multilingual acceptance. Hosted checks
and release remain pending; no deployment or protected merge is claimed.

RED `85a0b2d2` exposed the missing HTTP measurement option (1 failed,
3.67 s). The working candidate compiles a separate PyO3 extension using the
workspace's existing pyo3 0.29.2 lock resolution. It introduces no new
third-party dependency. The first build failed because a field-level getter
attribute was invalid; explicit read-only getters corrected compilation.
Context7 lookup hit its monthly quota; local compiler/API checks were used.

The separate Rust receipt owns an Instant clock and state transitions. Python
only associates that receipt with the existing HTTP context and SQLite store;
it computes no durations or statistical estimates. Opt-in requires the native
extension and a configured durable store. The ordinary callback admission and
two direct SSE admissions establish scopes before the nonblocking capacity check.
Initial selection hooks cover _invoke, streaming, generated planning, and
plain/capability proxy candidates. These source hooks are not all validated.

The initial decision is synchronously committed before the native acknowledgement
timestamp is captured. A separate receipt is exported at scope exit; that export
cannot be its own acknowledgement. A process crash between these writes leaves
an initial decision without a receipt, which must remain in the unfinished
denominator. Persisted successful receipts alone are not an all-request sample.

Focused verification in the isolated local Python 3.14 environment: 4 tests
passed in 1.49 s. The real HTTP route's dispatch callback queries a separate
SQLite connection (never flush-on-read store.load), verifies the committed
decision, captures its native acknowledgement, and holds answer generation
behind an event. The final acknowledgement must equal that pre-generation value.
Other tests cover native invalid/duplicate acknowledgement, missing-store
startup rejection, write failure, snapshot isolation and secret-safe errors.
Controlled mock provider output is unit/integration evidence, not customer data.

Remaining before review/merge: direct coordinator/structured synthesis and all
SSE/provider paths need executable coverage; metadata must bind policy revision
and route mode; unsupported and selection/cancellation outcomes need complete
denominator tests; race size/contract/preparation and concurrency need negative
tests; both receipt kinds need an explicit retention/export contract. Validate
actual wheel installation outside the source checkout (the current editable
extension is not package proof). Add the Proposed ADR with the completed seam
inventory, dependency graph and rendering inspection. Do not claim production
instrumentation, p95, accuracy improvement, protected CI, or release.

## Admission and SSE follow-up

At candidate descended from `df6eb4a7`, ten focused tests passed in 4.72 s.
These include ordinary HTTP chat, direct chat SSE, direct Responses SSE,
actual race worker context propagation and full candidate-set identity, and
oversized-race rejection before acknowledgement. The first race test fixture
omitted the required group identity and correctly exercised sequential routing;
adding the operator-contract group activated the intended race path.

An immutable accepted_request row now precedes the capacity check. Export joins
that row with initial_decision and final decision_receipt rather than dropping
unfinished requests. Rows are append-only and not automatically pruned; operators
must retain them for reconciliation and archive after verified export. A storage
outage can prevent the admission itself from being recorded: opt-in then returns
503 before dispatch, states measurement_complete=false and reconciliation_required=true,
and requires external ingress evidence. The local export never claims all-ingress
completeness. This is a deliberate limitation, not a zero-duration observation.

The existing analytics snapshot carries the joined records only with measurement
enabled and retains its local-runtime labeling. A separate Rust clock remains
the only duration implementation. A trusted request_id argument is the explicit
port for PR #1105; until integrated, identity_source=measurement_scope is honest.
The policy snapshot is hashed; route_mode currently identifies the dispatch
kind/role, not a complete top-level requested-mode contract.

An isolated noneditable core install plus native wheel, outside the checkout,
passed six tests (one then-current test deselected) in 9.13 s. Both imports were
verified under the isolated environment's site-packages. That build used an
uncommitted candidate and is not final exact-head package evidence. Dependencies
resolved anew there; locked PyO3 remained 0.29.2. Rebuild the final commit before
release. No binary is committed.

Still unverified: cache-hit and other callback-bypassing accepted-request coverage,
all structured/coordinator/direct-provider paths, selection/cancellation/capacity
HTTP negatives, complete ingress reconciliation, transactional snapshot export,
declared retention window and actual release packaging workflow. No customer KPI
gain is established. The Proposed ADR and full rendering inspection remain due.

## Integrated request identity and indexed cohort checkpoint

At `fe2db40e`, receipt, persistence and debug/correlation suites passed together:
54 passed in 9.26 s. Normal merges preserve rollback owner #1108 at `129a6650`
and request identity owner #1105 at `b655fe1b`. The handler now owns one
measurement lifetime across repeated slot acquisitions, and passes its trusted
request identity explicitly. Embedding fallback tests observe one admission and
two backend selections; explicit validated-endpoint admission precedes embedding
candidate ordering. Other endpoints remain labeled first_execution_slot and
must not be assumed to include prior selection work.

`6e4f87aa` adds a shared per-race invocation identity: replicas deduplicate within
one invocation, while a second race in the same request remains a new attempt.
The regression first failed with one attempt instead of two, then passed.
The earlier route-mode-only deduplication is superseded.

The state store backfills null keys only for valid measurement JSON identities
inside its startup transaction, never overwrites non-null keys, and adds the
(kind, key, seq) index. Its 2,000-measurement-row unit fixture plus malformed
unrelated row retains all 2,001 rows. EXPLAIN for the actual phase query shows
kind/key index search; this is query-plan evidence, not a measured latency gain.
Export reads a bounded shared admission cohort, exposes sequence/truncation
boundaries and unresolved legacy identities, and never independently prunes
phase rows. Historical storage remains append-only pending an archival policy.

An exact `01ce9035` native wheel and separately built noneditable core package
passed 10 tests in 4.90 s outside the checkout with isolated imports. That proof
does not cover the later merged runtime: rebuild the final candidate again.

Outstanding semantic gap: structured triage and ranking-evidence embeddings may
invoke providers before the current task-selection hook. Initial provider
dispatch and final task-route decision must be distinguished; no current receipt
is evidence of the headline routing-decision p95. Cache hits, non-generation
operations, auxiliary dispatch, all preselection SSE failures and cancellation
paths still require complete request-boundary coverage and executable evidence.
No protected merge, production publication, or customer KPI gain is claimed.
# Auxiliary and package acceptance checkpoint (2026-09-09)

The later frozen `3b6dd47ebb0f88802bacdd302051d2f03e7d5003` full suite passed
3,442 tests with two skips in 771.43 s; its noneditable wheel-only receipt and SSE
identity matrix passed 33 tests in 14.21 s. Independent saturation inspection then
found chat streaming could call triage before acquiring capacity, despite a 503
response. This was present with measurement disabled too; sibling nonstream chat
and Responses streaming already rejected without a provider call.

The capacity repair holds one explicit chat-classification lease through either
the direct stream or conducted `_run` path. Request finalization releases the
lease if classification or trace validation exits early. It does not acquire a
second slot, release a slot it never acquired, or depend on measurement being
enabled. Actual HTTP RED covered saturation and early exits (three failures,
one passing control); the expanded enabled/disabled route/conduct/trace/error
matrix plus streaming, disconnect, identity, and trace regression tests passed
93 cases in 33.87 s. Those are local correctness results, not a latency gain.

At `9707a5e1`, focused receipt/persistence tests passed 41 cases in 8.43 s.
The Rust clock now separates provider-ready diagnostics from initial task-route
acknowledgement. Structured triage, generated planning, and pre-selection evidence
embedding remain inside the task-route interval. Evidence embedding after native
selection is labelled `post_decision_evidence_embedding`, including write-failed
selection; it is not subtracted or presented as preceding routing work. Answer
cache reuse has a distinct terminal outcome with absent provider timing values.
The bounded admission cohort exports auxiliary records with an explicit diagnostic
cap and truncation indicator. Historical retention remains unresolved.

The initial embedding test asserted inside a best-effort transport callback.
That assertion was swallowed by the existing best-effort path and prevented cache
fill, causing a test-induced warm retry. The corrected spy only collects values;
assertions run after the response. No descriptor invalidation was established.

Native packaging was rebuilt from the repository root with
`maturin build --locked --release --manifest-path rust/decision_receipt/Cargo.toml
--interpreter .venv/bin/python --out /tmp/co-decision-receipt-wheels`.
Rust 1.97.1, maturin 1.15.0, Python 3.14.6, macOS arm64 produced the native wheel
SHA-256 `e0bf63d790256c6d4eba8598c131d63188a994c899df5124bd9eadf2cc39c568`.
Its five ZIP entries contain only the receipt extension and distribution metadata;
the independently built core wheel has no overlapping files. A separate
noneditable installation outside the checkout passed all 20 receipt tests in
11.83 s using `python -I`, with both import origins under that environment's
site-packages. This proves that local artifact matrix only, not Linux/Python 3.12
hosted acceptance or a released package. The namespace was retained because the
suspected core-file collision was not observed in either inspected native wheel.

CI now installs locked native build tooling, builds the extension before the full
suite, validates disjoint wheel ownership before installation, and exercises the
wheel-installed HTTP receipt tests outside the checkout. The existing benchmark
import smoke is preserved. These workflow changes remain pending hosted evidence.
Full endpoint admission validation, cancellation/error-path coverage, deployed
retention/reconciliation, and customer accuracy/latency measurements remain open;
none of the unit or mock-provider evidence establishes a customer KPI gain.
