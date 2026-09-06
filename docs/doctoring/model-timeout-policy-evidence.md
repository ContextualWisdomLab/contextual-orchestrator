# Model timeout policy: evidence and unfinished acceptance

Observation date: 2026-09-06. Status: local implementation, not released.

## Buyer requirement

An ordinary model call has no implicit application-wide execution limit.
Administrators can eventually set, inspect, clear and restore an explicit
model-specific limit in seconds, with validated input, precedence, inheritance
and an auditable policy revision. Cancellation, provider termination and
administrator timeout must remain distinguishable. A termination reason is
not automatically an incorrect-answer observation for psychometric fitting.

## Verified scope

PR #1053 at `661ce8db75460c9f5752ba1493aad026e01f5316` removes the implicit
client timeout and preserves null through existing waiting boundaries. Its
full suite completed with 3400 passed, 2 skipped, exit 0, in 918.02 seconds.
Clean start/end revisions matched; parsed JUnit had 3402 cases and no errors
or failures. This is software regression evidence, not buyer response latency
or a deployed recovery claim. Real Edge inspection covered the PR body only.

Local `439da2e585e11dfbd24911984ee1b82b29f8094d` adds durable configuration
using the existing normalized agent store, not a second settings service.
Eleven policy cases plus twenty existing pool cases passed in 10.23 seconds.
The tests exercise null defaults, invalid input, actual stored rows, migration,
restart, omission, clearing and rediscovery preservation. A large integer
binding failure was first reproduced at `dac678c1`, then corrected by
normalizing validated seconds to floating point. This does not establish that
every representable value is executable by a future transport clock.

The first related run at `c276fcec` had 28 passes and one existing HTTP test
timeout. Its isolated rerun passed, but the timeout cause is unconfirmed. Both
results are retained. The initial migration/large-value checks at `94c6856c`
could replay seeds without proving persisted rows; their pass is not counted
as durable-storage evidence.

## Reproduced audit failure and local transactional repair

At `6236e982`, the committed policy suite reports 1 failed and 11 passed in
4.72 seconds. Injecting an audit-storage exception during a 7200-second update
raises an error to the caller, yet both the serving candidate and a fresh
instance read 7200.0 rather than the previous null. This is a direct internal
configuration-path reproduction, not an externally admitted HTTP exploit:
HTTP create/PATCH allowlists still reject the new field.

The reproduced pool save committed before the general audit append, which uses a
separate state-store transaction. Moving the audit earlier cannot prove atomic
success, and blindly restoring a prior value could overwrite a concurrent
update. The next implementation must make policy revision/history and the
configuration change atomic at their owning store, with failure injection and
concurrent-update checks. General telemetry must not be mistaken for the
authoritative policy history.

Local `4e839ce1` now commits timeout history and the configuration change on
the same pool connection, then publishes the in-memory candidate. Existing
rows receive a timeout-only update, preserving unrelated stored attributes.
Changing policy requires a durable store and a separate timeout-only patch.
The generic audit stream no longer owns this policy transaction. A database
trigger that rejects history insertion rolls back the associated policy write,
including initial-row creation. The failure test now targets that actual
transaction rather than the former generic audit callback; the original
failure remains preserved in the earlier commit and JUnit.

At `c3879439cd4a0547ff06e7cbe8561cce787e3a1f`, 37 related cases passed in
2.65 seconds, exit 0. They cover rejection on history failure for both missing
and existing rows, ordered old/new values, durable-store requirements, a
stale writer with a different committed timeout and preservation of other
stored model attributes. This is not complete concurrent-policy correctness:
value-based conflict detection does not detect an ABA change, and serving
snapshots across processes do not yet carry a policy revision. Authenticated
actor evidence, revision-based restore and complete concurrency/commit-failure
injection remain required before exposing administrator policy writes.

The ABA limitation was then directly reproduced at `ef76ade9` (1 failed,
17 passed, 0.50 seconds). `d911a38e` reuses each model's latest history sequence
as its policy revision and compares it inside the write transaction, rejecting
a stale snapshot even when the value returned to null. Related tests passed
38/38 in 4.30 seconds. Revision allocation remains owned by committed history.

At `bceaeb23`, a deterministic interleaved WAL writer showed that loading model
values and history in separate reads could attach revision 2 to the old
3600-second value (1 failed, 18 passed, 6.88 seconds). `e5e9c96f` starts a read
transaction before selecting model rows, so values, relations and revisions
come from the same database snapshot. The same interleaving now returns
3600 seconds with revision 1; 39 related tests passed in 4.43 seconds, exit 0.
This proves that interleaving, not all distributed serving coherence. Policy
restore, authenticated actor attribution, complete concurrent-write failure
coverage and actual runtime enforcement are still unfinished and unshipped.

`c08a5fd5` adds nullable opaque actor evidence to the same policy-history
transaction. The corrected RED at `c1b372df` reached the missing actor argument;
earlier `cbab94c8` and `e0dc4209` failed because of test-header casing and a
missing authorization argument, not product behavior. A test first authorizes
the administrator fixture with SecurityConfig, then passes its principal digest
to the configuration boundary and checks the stored value contains no bearer.
This is component composition, not an authenticated HTTP policy-write E2E.

The caller-supplied actor must have the existing 64-character lowercase digest
shape when present. Legacy/internal records can remain null and are explicitly
unattributed. Static-token mode identifies a deployment principal, not an
individual human; individual attribution needs the configured identity resolver.
The actor migration does not invent identities for historical rows. HTTP write
admission must require authenticated actor evidence when enabled; it remains
closed until runtime enforcement and restore acceptance are complete.
At `fc234020`, 45 related tests passed in 7.18 seconds, exit 0, including
raw/malformed actor rejection and migration of an existing unattributed row.

## Remaining delivery gates

- Complete revision-based change/history and restore with authenticated actor evidence.
- Resolve request snapshot, precedence, inheritance and in-flight update rules.
- Bind actual execution to the released canonical Rust runtime contract;
  do not add a Python timer clone or consume an unreleased owner branch.
- Distinguish model response waiting from DNS, connection, pool and body-safety
  budgets. Preserve destination validation and DNS pinning.
- Verify streams, tools, local queues, embedding and endpoint races, including
  cancellation classification and resource cleanup.
- Only then admit HTTP writes and expose administrator controls; perform actual
  visual inspection and authenticated end-to-end tests.
- Re-run exact-head checks and independent reviews before protected merge,
  release, consumer pinning and deployed-version verification.

EgressWeave's inspected main `bd0339bf43cf5041e861bac86a84cb6e7e32637e`
documents finite phase ceilings that replace null values. That contract is not
silently compatible with unrestricted model response waiting. GitHub release
and tag queries were empty; this says nothing about every other registry.
Existing security PRs #220 and #210 are preserved; their historical review
comments do not establish a current writer lease.

Local raw evidence is retained under `/tmp/co-uptime-path.T7v9Rj/`, including
the original failures and JUnit reports. These temporary paths are not public
release artifacts. The local policy delta remains unpushed pending the gates
above; the remote PR's completed full-suite result applies only to `661ce8db`.

## Source reference

ContextualWisdomLab. (n.d.). *Finite outbound request-timeout boundaries*
(revision bd0339bf43cf5041e861bac86a84cb6e7e32637e). EgressWeave.
https://github.com/ContextualWisdomLab/EgressWeave/blob/bd0339bf43cf5041e861bac86a84cb6e7e32637e/docs/research/request-timeout-boundaries.md
