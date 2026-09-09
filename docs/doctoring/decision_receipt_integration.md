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
