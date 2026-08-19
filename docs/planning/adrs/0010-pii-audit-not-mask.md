---
id: "0010"
title: "Stop masking PII in API responses; keep only credential redaction"
status: accepted
proposed_date: "2026-08-19"
accepted_date: "2026-08-19"
deciders:
  - "repository maintainer"
consulted:
  - "governance-risk-compliance (org PII policy owner)"
informed:
  - "downstream consumers (naruon, gyeot, scopeweave)"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "tests/test_security_hardening.py"
effort: S
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0007-sast-transport-and-sql-hardening.md"
    relation: informational
asr_triggers:
  - kind: correctness
    evidence: "SECRET_PATTERNS included an unconditional email-address regex, and _response_payload applied redact_value to every API response regardless of caller or purpose, replacing every email address in every response with [REDACTED]."
    note: "Any downstream consumer whose product surface needs real content containing an email address (e.g. an email client) received corrupted data from every response this gateway served."
success_criteria:
  - metric: "email addresses in gateway responses"
    target: "redact_text masks credential shapes (API keys, tokens, passwords, bearer headers) only; email addresses pass through unchanged"
    measurement_window: "every redact_text/redact_value call"
    source: "tests/test_security_hardening.py::test_redaction_masks_credentials_but_not_email_pii"
---

# Stop masking PII in API responses; keep only credential redaction

## Context

`contextual_orchestrator/orchestrator.py`'s `SECRET_PATTERNS` mixed an
email-address regex in with genuine credential patterns (API key, token,
password, bearer header), under a function named `redact_text` whose
docstring said it masked "secret and personal-data shapes." `server.py`'s
`_response_payload` applies `redact_value` to *every* API response
unconditionally, with no caller-scope or purpose check.

The practical effect: every email address appearing anywhere in a chat
completion response, an orchestration trace, or an analytics/audit event
was replaced with the literal string `[REDACTED]`, for every caller,
always. This repo is the org's shared LLM gateway (consumed by `naruon`,
an email workspace, and other product repos) — any consumer whose actual
job requires the real content of a message (e.g. rendering an email's
sender address) received corrupted, unusable data from every response.

`governance-risk-compliance`'s own stated policy (its README) is explicit
on this exact point: PII is not masked; it is protected by purpose-limited
authorization, encryption, and audit logging.

## Decision Drivers

* Stop breaking every downstream consumer that needs real PII content to
  do its job — masking-by-default made the gateway unusable for its
  primary purpose for any content containing an email address.
* Keep genuine credential redaction (API keys, tokens, passwords, bearer
  tokens) — those are secrets, not user data, and must stay masked in
  traces regardless of caller.
* Match the org's already-decided PII policy rather than inventing a new
  one.
* Don't claim to have shipped a complete purpose-limited-authorization +
  encryption system in one pass when only the "stop destroying the data"
  and "audit trail already exists and is unaffected" pieces are done here.

## Considered Options

* Leave PII masking as-is and treat every downstream breakage as a
  separate bug in the consumer.
* Remove the email pattern from `SECRET_PATTERNS` entirely, relying on
  the existing audit-event trail (`_append_audit_event`,
  `record_analytics_event`) as the only immediate replacement control,
  and treat purpose-limited authorization + encryption as explicit,
  separately-tracked follow-up.
* Build a full purpose-limited-authorization and field-level-encryption
  layer for PII before removing the masking.

## Decision Outcome

Chosen option: "Remove the email pattern now; audit trail is the
immediate replacement control; authorization/encryption are tracked
follow-up, not silently declared done."

| Driver | Leave masking | Remove now, audit-only | Full auth+encryption first |
| --- | --- | --- | --- |
| Unblocks downstream consumers | No | Yes, immediately | No, blocked on a larger build |
| Matches org PII policy | No | Partially (audit leg only) | Yes, once complete |
| Honest about scope | N/A | Yes — follow-up items explicit below | Would overstate what's built |

`SECRET_PATTERNS` no longer contains an email-address regex. `redact_text`
now masks credential shapes only; its docstring says so explicitly and
explains why PII is excluded. The existing audit-event and analytics-event
recording (`TaskOrchestrator._append_audit_event`,
`record_analytics_event`) is untouched and continues to run — it is the
audit leg of the org's policy, already present before this change.

**Not done in this change** (explicit follow-up, not implied by this ADR):
purpose-limited authorization (scoping which callers/roles may see raw PII
in a response body) and field-level encryption of PII at rest. Both need
their own design pass — bolting them on inside this same change would
either be shallow (a fake gate) or scope well beyond a single-PR fix.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Every API response destroyed email addresses via unconditional redaction. | Remove the email pattern from `SECRET_PATTERNS`. | Implemented in current head |
| `redact_text`'s docstring overstated PII protection that didn't actually apply per-purpose. | Rewrite the docstring to state exactly what is and isn't masked, and why. | Implemented in current head |
| No purpose-limited authorization exists for who can see PII in a response. | Design and implement caller/role-scoped access control for PII-bearing fields. | Not started — follow-up |
| No field-level encryption exists for PII at rest in stored traces/analytics. | Design and implement encryption for PII fields in the audit/analytics store. | Not started — follow-up |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A future contributor re-adds a blanket PII regex to `SECRET_PATTERNS`, assuming that's how PII should be handled here. | medium | medium | This ADR plus the `redact_text` docstring explain the actual policy; the regression test pins the expected non-masking behavior. | maintainer |
| Purpose-limited authorization / encryption follow-up never gets built, leaving the org's stated policy only partially implemented indefinitely. | medium | high | Tracked explicitly in `conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md` as an open item, not silently closed by this ADR. | maintainer |
| Genuine secrets (API keys/tokens) accidentally stop being redacted alongside this change. | low | high | `SECRET_PATTERNS`'s two remaining credential patterns are untouched; `test_redaction_masks_credentials_but_not_email_pii` asserts the credential is still masked in the same call that leaves the email intact. | maintainer |

## Rollback / Exit Strategy

If a specific caller/route genuinely needs PII masked (e.g. a public,
unauthenticated demo endpoint), scope that as purpose-limited
authorization on that route rather than reverting this ADR — re-adding a
blanket regex to `SECRET_PATTERNS` would reintroduce the exact problem
this ADR fixes for every other caller.

## Affected Components

* contextual_orchestrator/orchestrator.py
* contextual_orchestrator/server.py
* tests/test_security_hardening.py
* docs/planning/adrs/0010-pii-audit-not-mask.md

## More Information

* `governance-risk-compliance` repository README (org PII policy: purpose-limited authorization, encryption, and audit — not masking).
* `conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md` (tracks the purpose-limited-authorization and encryption follow-up).
