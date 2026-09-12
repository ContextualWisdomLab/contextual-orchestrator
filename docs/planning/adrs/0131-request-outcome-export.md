---
id: "0131"
title: "Export reproducible prompt-free request outcome associations"
status: proposed
proposed_date: "2026-09-09"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
---

# Export reproducible prompt-free request outcome associations

## Context and Problem Statement

An operator can observe an admitted request and a completed job yet cannot join
them using a supported export. `/admin/state` deliberately shortens workflow
records, and batch associations were available only to recovery/internal state
readers. Reading raw persisted payloads exposes unnecessary content and cannot
be a customer-facing workflow. Existing keyed workflow replacement also removes
old rows, so a sequence cutoff over those rows cannot reproduce an earlier page.

## Decision Drivers

Preserve missing/failure denominators, stable pagination, original cache
classification, existing persistence rollback, and least-privilege disclosure.
This is security-, maintainability-, and reliability-significant; it does not
introduce an estimator or change routing decisions.

## Considered Options

1. Join current keyed workflow payloads: smallest read change, but replacement
   removes previously visible associations. Rejected after `c57efb79` RED.
2. Add a second export database/service: independent lifecycle but unnecessary
   synchronization, deployment and recovery obligations. Rejected.
3. Append minimal workflow metadata in the source transaction in the existing
   journal and query existing batch events. Selected as the bounded proposal.

## Decision Outcome

`workflow_request_link` records request ID, workflow ID, first cache status and
source row sequence, with no prompt, answer, owner digest or provider settings.
The source write and first association commit together; the unique workflow
origin index makes replacement idempotent and rejects origin reassignment.
No backfill invents history for pre-projection workflows.

The HTTP export requires the existing **service-wide admin role** and uses the
route-owned `audit_replay` purpose with durable authorization auditing. The
external bearer verifier receives `(token, scope)`, not a purpose claim. This
does not assert independently verified audit-purpose claims. Admin sessions and
the documented single-token local mode retain existing admin capabilities.
Inference/trace/operator-only credentials do not gain this capability.

Owner-scoped export is deferred: admission records do not carry a trusted owner.
Neither request IDs nor matching result records establish an admission owner.
Do not silently reuse an owner-replay endpoint for global evidence.

Pagination fixes a committed journal allocation high-water and advances admitted
sequence IDs. The existing AUTOINCREMENT allocation record survives pruning;
late links remain outside the issued cutoff. Only immutable associations are
used, not deleted historical workflow versions. Fixed pages are reproducible
while the retained admission/association evidence remains unchanged; external
database alteration or archival is outside this version's guarantee.

## Consequences

Positive: operators can reconcile retained admissions with workflow/batch handles
without extracting content, and replay pages after source replacement/restart.
Negative: one extra metadata record per linked workflow and two startup indexes
increase write/storage and migration costs. Service-wide metadata is sensitive:
identifiers may themselves be meaningful, so this is prompt-free, not certified
PII-free. Historical missing associations remain unresolved. Export caps disclose
truncation and do not constitute a complete cohort when any cap is reached.

## Confirmation and Rollback

The runbook records real HTTP, restart, role rejection, late completion, keyed
replacement, malformed metadata and transactional failure checks. Local tests
are not hosted approval, installed-package acceptance or customer accuracy.
The indexes are created in the existing startup migration transaction. Failed
migration rolls back without deleting records. Runtime rollback can disable the
new route and return to previous code while retaining journal events and indexes;
never delete durable evidence to roll back an API. Old code ignores the new kind.
If disk growth requires archival, define a versioned retention/export contract
before pruning these rows; do not invalidate issued cutoffs silently.

## More Information

SQLite. (2024). *SQLite autoincrement*. https://www.sqlite.org/autoinc.html

SQLite. (n.d.). *Indexes on expressions*. https://www.sqlite.org/expridx.html

See [API/PRD/TRD and sequence](../../doctoring/request_outcome_export.md).
Number 0131 was absent from the union of fetched local/remote branch ADR trees
at allocation; recheck current heads before publication. Status remains Proposed.
