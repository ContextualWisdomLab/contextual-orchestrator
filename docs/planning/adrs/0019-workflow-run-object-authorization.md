---
status: accepted
date: 2026-08-20
decision-makers:
  - contextual-orchestrator maintainers
---

# ADR 0019: Bind workflow evidence to the authenticated principal

## Decision

Treat workflow runs, access reports, evaluation runs, and workflow-derived
spend analytics as owner-scoped objects. At the authenticated HTTP boundary,
derive a non-secret SHA-256 key
from the authenticated deployment principal, attach it to newly persisted
records, and require the same key for list and detail reads. Static split
admin/inference credentials are normalized to one deployment principal so the
admin evidence plane can read runs created by the inference plane. An owner
mismatch is intentionally reported as not found so identifiers cannot be
confirmed across owners.

The library API continues to support local single-process callers that omit an
owner key. HTTP callers do not omit it. For an external bearer verifier, the
key is derived from the verified issuer and subject claims, never from the
bearer credential. Token rotation that preserves those claims therefore keeps
the same owner boundary; an issuer or subject change creates a different owner.

## Consequences

- A bearer cannot use a guessed workflow identifier to read another owner's
  trace or access report.
- The authenticated spend endpoint aggregates only runs owned by its bearer;
  the local library API may still omit an owner to request process-wide totals.
- Its process-wide budget and owner totals are derived in one run scan, so the
  displayed cap state cannot drift from enforcement during a concurrent update.
- Admin audit events that reference workflow or evaluation runs follow the same
  resource owner boundary; global agent-configuration events remain visible.
- Reported prompt-token totals follow the same owner filter as runs and output
  tokens, and access-report analytics are emitted only after ownership succeeds.
- The stored digest is an authorization lookup key, not a user identity and is
  never rendered in public payloads.
- Shared static credentials represent one deployment principal; multi-principal
  deployments must issue distinct verified bearers. External bearer deployments
  use the verified `iss`/`sub` pair as principal material before hashing, so
  normal credential rotation preserves access to that principal's evidence.
- Old records without an owner key are not visible through the owner-bound HTTP
  resource routes, which is fail-closed during migration.

## Acceptance evidence

Owner mismatch, list filtering, evaluation ownership, stable principal-digest
derivation, and response redaction are covered by
`tests/test_workflow_run_object_authorization.py`. External-bearer spend and
audit isolation, shared-budget truthfulness, and single-scan consistency are
covered by `tests/test_spend_analytics.py`.

## References

Open Worldwide Application Security Project. (2023). *OWASP API Security Top
10: 2023 (API1:2023 Broken Object Level Authorization).*
https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/

National Institute of Standards and Technology. (2020). *Digital identity
guidelines: Authentication and lifecycle management* (SP 800-63B).
https://doi.org/10.6028/NIST.SP.800-63b
