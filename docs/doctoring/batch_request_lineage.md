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
