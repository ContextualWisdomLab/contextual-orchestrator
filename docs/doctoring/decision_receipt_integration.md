# Initial decision receipt integration candidate

Status: incomplete implementation for issue #1110; not release evidence.

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
