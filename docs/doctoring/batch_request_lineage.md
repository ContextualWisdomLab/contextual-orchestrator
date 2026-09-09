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
