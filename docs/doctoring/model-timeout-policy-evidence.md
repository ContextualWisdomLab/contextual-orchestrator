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

## Confirmed unresolved audit failure

At `6236e982`, the committed policy suite reports 1 failed and 11 passed in
4.72 seconds. Injecting an audit-storage exception during a 7200-second update
raises an error to the caller, yet both the serving candidate and a fresh
instance read 7200.0 rather than the previous null. This is a direct internal
configuration-path reproduction, not an externally admitted HTTP exploit:
HTTP create/PATCH allowlists still reject the new field.

The current pool save commits before the general audit append, which uses a
separate state-store transaction. Moving the audit earlier cannot prove atomic
success, and blindly restoring a prior value could overwrite a concurrent
update. The next implementation must make policy revision/history and the
configuration change atomic at their owning store, with failure injection and
concurrent-update checks. General telemetry must not be mistaken for the
authoritative policy history.

## Remaining delivery gates

- Implement atomic change/history and restore with authenticated actor evidence.
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
