# Deferred batch request lineage

## RED reproduction, 2026-09-09

Base `af8d732e6cfc9c0169ac850f875f42f1db7eecd4`; test commit
`387aa211` on isolated branch `codex/batch-request-lineage-20260909`.
Command: `.venv/bin/python -m pytest tests/test_batch_request_lineage.py -q`.
Terminal result: **1 failed in 3.75s**. Submission returned HTTP 201;
retrieval returned HTTP 200 with two distinct caller custom IDs. Passive backend
observations confirmed distinct trusted submission/retrieval request identities.
After closing and reopening SQLite, the proposed submission/job/item association
was absent: an empty set instead of two links. No runtime implementation changed.

This test proposes the `batch_request_link` association shape; that shape is not
an existing released contract. It demonstrates the missing durable association,
not a defect in an already-promised schema. The fixture reuses the existing
offline pg-llm-batch client double. No external model was invoked. This is not
remote integration, process-restart batch execution, numerical accuracy, or latency
evidence. The fixture preserves results in test memory across state-store reload;
it does not claim that the default in-memory batch registry survives restart.

The smallest repair belongs in CO's submission coordinator and durable job
association boundary, with a trusted identity argument from the HTTP adapter.
Preserve multiple submission/job/item associations and keep provider custom IDs
separate. Do not reassign origin when a later HTTP request retrieves outcomes.
Remote execution provenance requires the released pg-llm-batch contract separately.

Environment: project-local Python 3.14.6, dependencies synchronized with
`uv sync --frozen`. An initial pytest-only environment failed collection because
certifi was absent; this was an environment error, not the RED result. The attempted
`uv sync --frozen --group test` was invalid because test is an optional extra,
not a dependency group; the frozen default synchronization repaired collection.
CodeGraph initialization completed (438 files); no other worktree was modified.

## Candidate implementation and review repair

`62239624`: focused lineage, batch backend, and cost-review HTTP tests passed
**42 tests in 12.33s**. Includes existing cross-principal denial coverage.
The initial status/failure contract at `919c945a` failed twice in 1.54s; initial
implementation `9356ac62` passed 39 tests in 14.35s. Follow-up repeated-origin,
repeated-retrieval and no-store cases passed 41 tests at `b565173e` in 11.63s.

The association is an append-only typed event in the existing state store:
`request_id`, `batch_job_id`, `custom_ids`, and `owner_id`. A single event commits
the complete submission cohort using the existing rollback-safe transaction.
Consumers project one association per custom ID; this replaces the original
RED's proposed per-item event shape. It is not a new relational entity claimed
to satisfy 3NF. Item IDs remain job-scoped and repeated submissions append,
never replace prior origins. No prompt or answer enters the event.

HTTP 201 means the upstream job was submitted, not that all local state is
durable. `request_link_status` is `durable`, `write_failed`, or `unavailable`.
After remote success, a failed association commit returns the original handle
with `write_failed` and no raw exception. It never automatically resubmits.
No-store/library calls remain supported with unavailable lineage. This response
diagnostic is not reconstructed from remote registry snapshots after restart;
the committed association event is the durable evidence.

Review found an added second registry assignment could lose the successful
remote handle behind a new exception. Regression `b5baf420` failed once in
0.39s; `62239624` removes that assignment. Existing Valkey writes are separate
`hset` and `expire` calls, not atomic with SQLite. Failure of the original
registry assignment after remote submission remains an unresolved existing
ambiguity; no cross-store transaction, complete recovery, retention/export
window, API reconciliation surface, or remote integration is claimed here.
The event is currently only consumed by the test projection. Full-suite,
package, hosted checks, independent approval, and protected release are pending.

## Recovery successor (supersedes status-only limitations above)

Actual HTTP restart regression `d71bcc0a` failed once in 1.96s: an accepted
remote job returned 201 despite a failed registry write, but its rightful owner
received 404 after restart. A different authenticated owner also received 404.
This established unrecoverable work, not just missing status metadata.

Candidate `853e8609` passes **73 focused tests in 21.17s** across lineage,
batch routing, cost-review HTTP, and registry files. New coverage distinguishes
HSET failure (no handle stored) from expiry failure (HSET partially applied),
and returns the original upstream handle without a second submission. Earlier
`18af2947` expiry tests incorrectly inspected an unprefixed fake-registry key;
`b12981d6` corrected the test and passed ten cases in 6.18s.

The single durable submission event now includes a prompt-free recovery
descriptor: exact backend name/endpoint alias/endpoint, owner-bound job snapshot,
original token estimates, expected job-scoped item IDs, model/mode/normalized
attribution, and expiry tied to the configured registry retention. This is only
supported for PgLlmBatchBackend, not arbitrary local or embedding backends.
No prompts or credentials are included. Absent source messages remain unavailable;
their contents are never fabricated for token estimates.

An indexed exact-key lookup permits the original owner to recover a missing
registry handle after SQLite reload. Wrong owner, expired descriptor, malformed
backend object, or changed backend target fail closed. Restored expected item
IDs retain the existing response-identity validator; unexpected result IDs are
rejected. Missing usage remains estimated or unavailable, never relabeled measured.
The malformed-backend test initially returned 500 at `65b41603` (one failure,
five passes in 9.90s); explicit type validation changed that to a concealed 404.

Request-link status is finalized before the single registry write and survives
Valkey decoding consistently. Registry-write outcome is response-only and is
excluded from dataclass serialization, since HSET may apply before expiry fails.
`stored` means that configured registry operation returned, not proof of process
restart durability for a local dictionary. HTTP 201 still means remote submission;
clients must preserve the handle and must not resubmit solely because local
persistence is incomplete. If both SQLite and the registry fail, automatic recovery
remains unavailable. This is a tested recovery slice, not complete cross-store
atomicity, retention cleanup, production integration, or customer KPI evidence.

## Independent review repairs and injected-adapter configuration

At `a6b94855`, the four-file focused suite passes **84 tests in 32.63s**.
Intermediate failures and successful checks remain attributed to their commits:

| Source | Check | Result |
| --- | --- | --- |
| `e372bc54` | Registry outage, inconsistent item IDs and estimate keys | 3 failed, 3.59s |
| `7fb1a71c` | Lineage file after recovery isolation | 19 passed, 14.94s |
| `83394afa` | Malformed job fields and deployment binding added | 23 passed, 18.26s |
| `f4d036bf` | Healthy coordinator handle, missing backend metadata | 1 failed, 1.37s |
| `6cb530a7` | Four-file suite | 81 passed, 29.90s |
| `42ad396c` | Duplicate persisted item IDs | 1 failed, 1.52s |
| `aaa9b133` | Four-file suite | 82 passed, 31.21s |
| `17cfa611` | Backend registry write fails after remote creation | 1 failed, 0.95s |
| `8ddfeb9f` | Same backend-failure HTTP test | 1 passed, 1.79s |
| `df638d6c` | Healthy active job with expired recovery descriptor | 1 failed, 1.51s |

The Pg adapter now retains the upstream handle even when its own metadata
registry write fails before returning to the coordinator. The response separates
`backend_registry_persistence_status`, `registry_persistence_status`,
`request_link_status`, and `recovery_status`. The first two describe individual
write outcomes, not restart durability. HSET may apply before expiry fails;
response-only write results are not serialized as claims about their own writes.
Missing durable lineage still remains explicit; no handler repeats submission.

Recovery tolerates continuing coordinator/backend registry outages. Validated
item metadata is carried on the returned job for that retrieval, without writing
back through the failed registry. The stored envelope's item list, descriptor
items, job count, and estimate keys must agree before downloading. Invalid count
types and null estimates fail closed. A healthy authorized registry job retains
its original refresh-on-read lifecycle even if its separate fixed-deadline
recovery descriptor has expired; missing metadata cannot use expired recovery.

There is no built-in production Pg adapter constructor in this source tree:
the CLI/default coordinator uses the local backend. Integrators injecting
`PgLlmBatchBackend` configure its optional `recovery_identity` argument with a
stable, non-secret service/deployment/account identifier. Keep this identifier
stable during credential rotation and change it when the service or account
changes. Do not use a credential, infer equivalence from an endpoint alias, or
accept an HTTP caller's value. The default `None` disables durable recovery,
and submission reports `recovery_status=unavailable`; a committed, explicitly
bound Pg descriptor reports `durable_descriptor`. A different or missing binding
cannot recover the old job, even if endpoint aliases are identical.

The real-HTTP tests use offline injected clients; no deployed integration is
claimed. Simultaneous loss of both durable submission evidence and job registries
still cannot promise recovery. Full suite, clean wheel, hosted review and release
remain pending. Do not stop at a status-only response when recoverable evidence
exists, and do not label a retained remote handle complete recovery by itself.

## Final focused acceptance before full regression

Runtime `45066759`: **86 passed in 36.58s** across the four focused files.
The last review exposed inconsistent endpoint binding on healthy metadata:
`c06615ab` failed once in 2.09s. New metadata now stores the exact endpoint and
stable deployment binding before the healthy fast path can use it. A changed
binding, changed endpoint, or missing binding on opted-in metadata cannot bypass
the validated descriptor path. This fixes a contract inconsistency; no cross-service
data leak was established by the offline test. Unbound legacy metadata remains
compatible only with an unbound backend; its missing identity is never described
as validated recovery. The legacy-focused suite passed 85 tests in 35.09s at
`2d68f705`. Independent review accepted freezing this bounded implementation for
full regression and separate installed-artifact verification, not publication.
