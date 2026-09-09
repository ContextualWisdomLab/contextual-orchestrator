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
