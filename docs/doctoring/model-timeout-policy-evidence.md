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

Restoration was first missing at `2919652e` (2 failed, 25 deselected, 2.26
seconds). Local `37bca9ca` adds a model-scoped historical lookup and restores
its value through the same revision-checked policy transaction. The new history
row references its source revision and supplied actor; existing rows remain
unchanged. Both the expected current revision and the model owning the source
history are checked. No HTTP restore endpoint is admitted yet.

At `62ba3c3b`, 54 related tests passed in 6.65 seconds, exit 0. They include
restore success as a new revision, stale-view rejection, foreign-model history
rejection, malformed revision rejection and history-insertion failure rollback
for both durable value and in-memory revision. This is local storage/domain
evidence. Authenticated HTTP restore, user-facing history/restore controls,
multi-process serving refresh, complete concurrency and actual model execution
enforcement remain required before release.

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

## Ordinary-save policy protection

At `e0eab787`, a stale orchestrator's priority edit was accepted after another
writer set a 7200-second policy (one failed test, 1.12 seconds). The ordinary
pool UPDATE included the stale timeout without appending policy history.
At `9701dec2`, every pool save checks the policy value and revision inside the
existing immediate transaction before writing. A stale ordinary edit now fails
before publishing its candidate; the durable policy and history remain intact.
The policy, pool database, and governance suites passed 60 tests in 4.09 seconds.
This is focused storage-boundary evidence, not distributed refresh, runtime
deadline enforcement, HTTP authorization, or a new full-suite result.

A fresh visual-inspection attempt on 2026-09-06 could not proceed because the
Mac was locked. Earlier remote PR screenshots do not verify these local changes.

## Serving publication after rejected pool edits

At `1edf0fba`, three regressions reproduced removal, group assignment and group
deletion changing the in-memory serving candidates despite a rejected stale
policy save (3 failed, 35 deselected, 0.70 seconds). At `befe04ce`, these callers
publish candidate lists and reset routing state only after durable saves.
Policy, pool, governance, model-group and mixed-role-effort suites passed
103 tests in 15.34 seconds, exit 0. No full-suite or transport claim follows.

Multi-model group/discovery writes still commit one row at a time. A later
failure may leave earlier durable rows changed even though serving publication
is withheld. Batch rollback and concurrent serving refresh remain open gates;
the single-target regressions above do not prove either requirement.

## Multi-model transaction rollback

At `ad337e18`, group assignment, group deletion and discovery each reproduced
a partial durable write when the second model had a stale timeout revision:
3 failed, 38 deselected, 2.78 seconds. The first model remained changed after
restart even though the operation failed and memory remained unchanged.

At `36fc35df`, single and batch saves reuse the same per-connection normalized
write body. Each group/discovery operation uses one immediate transaction;
any exception closes the uncommitted connection and rolls back earlier rows.
The three reproductions and policy/pool/governance/group/mixed-role/bootstrap
boundary suites passed 122 tests in 5.04 seconds, exit 0. This supersedes the
per-row group/discovery rollback gap above, but not cross-process serving
refresh, separate bootstrap operations, audit streams outside the pool, or
actual model deadline enforcement. No new full-suite result is claimed.

## Authenticated HTTP conflict boundary

At `a2951f67`, an actual loopback HTTP server and a separate orchestrator sharing
the pool database verify: an invalid bearer gets 401; an authenticated stale
priority PATCH gets 400 with reload guidance; a direct timeout PATCH remains
400 because the new write field is not admitted. Serving candidates remain
unchanged and restart retains the other writer's 7200-second policy/revision 1.
The focused test passed in 4.01 seconds (1 passed, 20 deselected, exit 0).
This proves existing HTTP rejection, not authenticated policy-write success,
automatic serving refresh, actual inference selection, or deadline enforcement.

The EgressWeave protected-main SHA was rechecked as `bd0339bf` and its GitHub
release listing returned no entries. DeepWiki returned repository-not-found;
neither result proves absence from every registry or absence of another writer.
Runtime-owner coordination remains open; no consumer transport clone was added.

## Canonical runtime dependency request

The owner PRD/TRD at `bd0339bf` explicitly require finite request-phase waits
and describe a Python runtime. Model response lifetime therefore requires an
explicit Proposed contract change, not merely passing null into current APIs.
The required Rust owner behavior, separate total/read deadlines, cancellation
causes, resource/security invariants and five behavioral RED families are
recorded in [the existing timeout-policy review lane](https://github.com/ContextualWisdomLab/EgressWeave/pull/220#issuecomment-5559695131).
This is a dependency request, not accepted architecture or implementation.

The visible owner worktrees were inspected read-only: Actions concurrency,
draft admission and #235 gateway migration are separate deltas. Their untracked
lock/index/desktop files were preserved. No owner branch was taken over; no
consumer source copy, release adoption or deadline activation occurred.

## Read-only operator policy view

`b80e64be` records the missing-route RED: authenticated GET returned 400 rather
than exposing a fresh policy view. `2e12ed46` reuses the store's transactional
snapshot for `GET /api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}/timeout_policy`.
It reports configured seconds/revision separately from the local serving
snapshot, with seconds as the explicit unit and `enforcement_available=false`.
Reading does not refresh routing, change policy or activate an execution limit.
The existing full-snapshot read is linear in pool size; this is an operator
read, not a routing hot path or an independently measured latency improvement.

At `6774dab4`, 88 pool/policy/security tests pass in 9.52 seconds. Actual HTTP
checks cover null defaults, a second writer's 7200-second revision, preservation
of the stale serving snapshot, wrong and inference-only credentials, and a
missing model. OpenAPI declares the admin-only contract and explicit inactive
enforcement state. That revision does not implement history pagination, write/
clear/restore HTTP operations, runtime integration or the administrator UI.

`80b3aa36` retains a missing-history-method RED. `5dc69bc1` adds a model-scoped
descending revision cursor and a model/revision index. At `f9505a5c`, 96 related
pool/policy/security tests pass in 7.70 seconds, including actual admin-only
HTTP history reads and invalid-bound rejection. A page contains at most 100
records. Newer insertions do not repeat or displace records on an older-page
cursor; another model's revisions never enter the result. Restore provenance,
nullable legacy actor digests and original timestamps are retained. An
in-memory-only pool reports history unavailable, not durable empty-history proof.
These are read-only operations; set/clear/restore HTTP actions, execution
enforcement and UI acceptance remain incomplete.

## Strix HTTP 500 and error correlation

The [Strix run 34031339200](https://github.com/ContextualWisdomLab/.github/actions/runs/34031339200)
installed CO `414f22973658c4ddc3d4320fcf7acd9b4e8ba991` (job log
1280–1281). Artifact `9991542931` contains sidecar failures at
14:53:36.102 and 14:53:54.577 UTC on 2026-09-06: `TimeoutError` at
`_open_provider`, then generic HTTP 500. At the installed revision, the
reported line 2281 waits for response headers. Strix reports failures within
12 milliseconds of those events. This is temporal correlation, not an exact
request-ID join: the sidecar does not contain either terminal response ID.
The 5377-second wrapper duration is not one model request's timeout.

`10225f43` first tested the authentication verifier failure incorrectly as a
500; the existing fail-closed boundary correctly returned 401. The corrected
`4b739339` test injects a generic handler failure and retains the actual RED:
concurrent responses contain unique IDs absent from their corresponding logs.
`0e7c03bd` reuses each error response's ID in the existing sanitized status/code
log. No new telemetry system, transport timer, provider retry or fallback is
introduced. Existing response details remain unchanged; noncanonical override
IDs are omitted from logs rather than copied as arbitrary text.

At `8c20f1e1`, 142 security, provider-error and passthrough tests pass in 14.36
seconds. They cover concurrent HTTP 500 correlation, existing ID preservation,
and rejection of arbitrary diagnostic text from logs. This is focused evidence,
not a full-suite or protected-release claim. SSE-specific error events remain a
separate correlation gap; this change addresses the ordinary HTTP error path.
The underlying raw transport exception/fallback boundary still needs repair
analysis separately from the default-null/model-lifetime contract.

An actual screen-access attempt still returned a locked Mac. Administrator UI
visual acceptance remains unverified; paper figure inspection is not UI proof.

## Source reference

ContextualWisdomLab. (n.d.). *Finite outbound request-timeout boundaries*
(revision bd0339bf43cf5041e861bac86a84cb6e7e32637e). EgressWeave.
https://github.com/ContextualWisdomLab/EgressWeave/blob/bd0339bf43cf5041e861bac86a84cb6e7e32637e/docs/research/request-timeout-boundaries.md
