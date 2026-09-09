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
