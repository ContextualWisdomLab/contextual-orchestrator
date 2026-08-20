---
id: "0011"
title: "Purpose-limited PII authorization and field-level encryption boundary"
status: proposed
proposed_date: "2026-08-19"
deciders:
  - "repository maintainer"
consulted:
  - "Keyverse deployment boundary"
  - "governance-risk-compliance (org PII policy owner)"
informed:
  - "downstream consumers (naruon, gyeot, scopeweave)"
affected_components:
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/credentials.py"
  - "docs/kv-credentials.md"
  - "tests/test_security_hardening.py"
  - "tests/test_state_persistence.py"
effort: L
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0003-keyverse-authentication-boundary.md"
    relation: constrains
  - path: "docs/planning/adrs/0010-pii-audit-not-mask.md"
    relation: follows
asr_triggers:
  - kind: security
    evidence: "The gateway now preserves PII in product responses, while audit and analytics details can still be persisted as generic JSON."
    note: "Authorization must be decided before decryption and plaintext PII must not be written to SQLite/Postgres or logs."
  - kind: privacy
    evidence: "Admin and inference are the only current bearer scopes; admin is not itself a valid business purpose for reading raw PII."
    note: "A route-defined purpose and principal claims must be evaluated together; arbitrary caller-supplied purpose headers are not authorization."
success_criteria:
  - metric: "raw PII response access"
    target: "only an authenticated principal with an allowed route purpose and field policy can receive a PII-bearing field; admin scope alone is insufficient"
    measurement_window: "every PII-bearing response route"
    source: "authorization and response-policy tests"
  - metric: "PII at rest"
    target: "database export and ordinary application logs contain no plaintext classified PII; authorized reads decrypt only after policy approval"
    measurement_window: "every audit/analytics persistence and read path"
    source: "SQLite/Postgres export, tamper, and authorization tests"
  - metric: "key lifecycle"
    target: "key version, rotation, revocation, retention, and rollback behavior are explicit and tested"
    measurement_window: "every encryption adapter and migration"
    source: "key-rotation and migration tests"
---

# Purpose-limited PII authorization and field-level encryption boundary

## Context

ADR 0010 stopped the gateway from destroying email addresses in every API
response. That was the correct data-integrity fix, but it deliberately did
not implement the other two legs of the organization's PII policy:
purpose-limited authorization and encryption at rest.

The current runtime has a useful but narrower boundary:

* SecurityConfig authenticates admin and inference bearer scopes, or delegates
  verification to a Keyverse/OIDC adapter through bearer_verifier(token, scope).
* _response_payload redacts credential-shaped secrets and optionally strips
  trace; it does not distinguish a PII-bearing field from an ordinary field.
* _StateStore persists audit and analytics events as JSON in one generic
  SQLite table. The same logical state can later be backed by another store.
* _append_audit_event and record_analytics_event may receive nested
  dictionaries. A database dump is therefore not evidence that PII is
  protected merely because response redaction is correct.

This ADR is a design boundary, not an implementation claim. Until the
acceptance evidence below exists, the follow-up remains incomplete.

## Decision drivers

* Preserve real PII for an authorized product response; do not reintroduce a
  blanket email/PII regex.
* Make the purpose of an access request a server-owned route property, not an
  untrusted header or free-form caller string.
* Keep Keyverse/OIDC protocol validation outside the stdlib gateway core, as
  required by ADR 0003.
* Encrypt only classified fields, so retention, deletion, and non-sensitive
  analytics remain operable.
* Fail closed on missing keys, unknown versions, invalid authentication tags,
  revoked keys, malformed envelopes, and authorization failures.
* Keep secrets, plaintext PII, bearer tokens, and decrypted error details out
  of logs and analytics dimensions.

## Proposed design

### 1. Principal and purpose are separate inputs

Replace the boolean-only production verifier result with an injected
Principal/authorization adapter contract. The adapter may be implemented by
the Keyverse deployment boundary; the core must not decode JWTs or own IdP
credentials.

The principal contains only verified, non-secret attributes needed by policy:

    subject_id, tenant_id, roles, scopes, authentication_source, token_id

It never contains the bearer token or client secret. Local static-token mode
may produce a low-trust local principal for development, but it must not
implicitly grant raw-PII access in a deployed environment.

Each protected route declares a finite purpose in code. Initial purposes are:

| Purpose | Route class | Default PII result |
| --- | --- | --- |
| inference.execute | model request/response | raw content allowed only for the authenticated tenant and policy-approved fields |
| audit.read | audit/event inspection | metadata and redacted detail only |
| audit.read.pii | exceptional support/compliance retrieval | decrypt classified fields only after explicit role, tenant, time-window, and case/reference checks |
| analytics.read | aggregate analytics | aggregates only; no raw PII fields |

admin is an authentication scope, not a purpose and not an automatic PII
grant. The policy decision receives (principal, purpose, resource,
field_classification, request_context) and returns an allow/deny decision
with a reason code. Callers cannot elevate themselves with X-Purpose or an
equivalent request header.

The route-purpose registry is validated at startup. Every protected route
must map to exactly one known purpose and an incomplete, duplicate, or
unknown mapping prevents the service from becoming ready. A protected route
with no registered purpose, or a request carrying an unknown purpose, is
default-deny; there is no permissive fallback. The server constructs
`request_context.tenant_id`, resource/case reference, and time window only
from verified principal claims, route metadata, and server-owned resource
state. Request JSON, query parameters, and headers may select a resource
identifier for lookup but cannot assert tenant, purpose, case authorization,
or time-window membership.

### 2. Classify fields at the producer boundary

Do not use a second blanket regex to guess whether every string is PII.
Producers of audit/analytics records must mark sensitive leaves with a
stable field classification, for example pii.contact, pii.content, or
secret.credential. The response policy can then decide whether a field is
returned, omitted, or decrypted without changing unrelated strings.

Credential redaction remains an independent output/logging control. A
credential-shaped secret is never returned even when the surrounding
purpose permits raw product content.

The producer boundary uses an allowlisted producer schema and field registry.
Each sensitive leaf must resolve to an approved classification such as
`pii.contact`, `pii.content`, or `secret.credential`; `pii.*` and `secret.*`
are not accepted merely because a producer supplied a string with that
prefix. `StateStore` rejects a write before persistence when a leaf is
missing a classification, uses an unknown classification, or disagrees with
the registered schema. A producer may explicitly register a non-sensitive
operational class, but an unclassified value is never silently stored as
ordinary JSON.

Log and metric sanitization is a separate control from `redact_text`.
Producer-field classifications drive removal or masking of classified PII
from structured logs, metric labels, traces, and generic error details;
credential redaction continues to protect secrets independently. Generic
errors expose only a stable code and correlation id, never the rejected
value, decrypted text, or provider exception detail.

### 3. Encrypt classified fields, not complete records

Inject a FieldEncryptor behind the existing KV/KMS boundary. Its ordinary
write API is intentionally narrow:

    encrypt(classification, plaintext, encryption_context) -> EncryptedField
    decrypt(principal, purpose, classification, envelope, encryption_context) -> plaintext

`EncryptionContext` is immutable and contains `tenant_id`, `record_kind`,
`field_path`, and `schema_version`; the adapter authenticates all four as
AEAD associated data. Ordinary callers cannot supply `key_version`. The
approved KV/KMS adapter selects the active version. An explicit target
version is accepted only by a separately authorized `reencrypt`/migration
operation that records its migration id, source version, target version,
and operator authorization.

The implementation must use an approved AEAD/KMS adapter and a unique nonce
per encryption. The application may carry ciphertext and envelope metadata,
but key material is resolved from the approved credential/KMS registry, never
from raw environment variables, persisted configuration, or logs.

The persisted envelope contains only:

    algorithm, key_id_or_version, nonce, ciphertext, authentication_tag, schema_version

For an AEAD with an appended tag, the storage adapter may keep the tag in the
ciphertext blob; the wire/storage representation must still make the
authenticated boundary explicit. Associated data binds the immutable
encryption context so ciphertext cannot be moved between tenants, record
kinds, field paths, or schema versions unnoticed. Decryption rejects a
context mismatch even when the envelope and key are otherwise valid.

StateStore serializes classified leaves into one canonical envelope before
the SQLite/Postgres write. The record shell may retain non-sensitive
timestamps, event names, correlation ids, retention class, and key version.
Do not encrypt an entire audit record when that would prevent retention,
indexing, deletion, or legal-hold controls.

The canonical generic-JSON representation is identical in SQLite and
PostgreSQL:

    {
      "type": "encrypted_field",
      "version": 1,
      "algorithm": "AES-256-GCM",
      "key_version": "active-key-version",
      "nonce_b64": "...",
      "ciphertext_b64": "...",
      "classification": "pii.content",
      "field_path": "payload.body",
      "schema_version": "2026-08-19"
    }

`type` is the discriminator, `version` is the envelope format version, and
every binary value is standard base64 text. The authentication tag is
included in `ciphertext_b64` for AES-GCM; an adapter using a detached tag
must use the separately approved `tag_b64` field instead. No unregistered
extra fields are permitted. Unknown envelope versions, algorithms,
discriminators, missing required fields, invalid base64, duplicate keys, or
classification/path mismatches are rejected on both write and read. The
canonical serializer and parser are shared by SQLite and PostgreSQL so a
database export cannot change the authenticated meaning of a field.

No plaintext search over encrypted fields is part of this design. If an
approved product requirement needs lookup, add a separate keyed digest with
an explicit leakage review; never add deterministic encryption merely to
make an ad-hoc query work.

Existing audit and analytics records require a separate migration before the
ADR can become accepted. The migration discovers all SQLite/PostgreSQL rows
and exports, applies the approved producer schema and classification
backfill, encrypts classified leaves into the canonical envelope, and
quarantines or fails closed on ambiguous records. It records counts and
digests, supports rollback before destructive cleanup, and verifies that no
classified plaintext remains in database rows, backups, or exports. Legal
hold and retention rows are included in discovery and verification; a
non-sensitive record shell remains available for deletion and retention
operations.

### 4. Read, audit, and failure behavior

The read path is ordered:

1. authenticate the request;
2. resolve the server-owned purpose and resource/tenant scope;
3. authorize the requested field classifications;
4. decrypt only the approved fields;
5. construct the response and apply credential redaction;
6. append an access-decision audit event without raw PII.

Any failure returns a generic authorization or unavailable response. It must
not reveal whether a particular person, email address, ciphertext, or key
version exists. Audit records contain subject_id, tenant, purpose,
resource/correlation id, field classification, decision, reason code, and
key version where relevant; they do not contain bearer tokens, plaintext
PII, or decrypted exception text.

The access-decision audit is durable before a PII-bearing response is
released. Where the store supports transactions, the audit event and
response release decision commit atomically. Otherwise a durable outbox entry
is committed first and the response is released only after the outbox write
is acknowledged. If audit persistence or outbox acknowledgement fails,
return a generic unavailable response and release no PII. Outbox replay is
idempotent, and a missing audit record is a release-gate failure, not an
operator warning.

### 5. Key lifecycle and migration

* New writes use the active key version from the KV/KMS adapter.
* Reads accept only explicitly supported versions and verify the AEAD tag.
* Rotation is bounded: write new version, re-encrypt eligible records in
  batches, verify authorized reads, then revoke the old version after
  retention and rollback windows.
* Before revocation, count and digest every live envelope reference to the old
  version across active rows, retention rows, legal holds, backups, and
  exports. If any reference remains, keep the old key in decrypt-only state;
  never revoke based only on a sample or on rows visible to the ordinary
  retention query.
* Revocation and missing-key behavior fail closed; a partial migration never
  silently writes plaintext.
* A migration must preserve record deletion and retention semantics and
  produce counts/digests, not plaintext samples.
* SQLite and Postgres adapters use the same logical envelope contract; a
  database export is part of the acceptance evidence.

## Threat model

| Threat | Required control |
| --- | --- |
| Inference caller requests audit data | Route purpose and resource policy deny; scope alone is insufficient |
| Admin caller requests all raw PII | admin does not imply audit.read.pii; explicit role/case/tenant policy required |
| Caller spoofs a purpose header | Purpose is selected by the server route, never trusted from request data |
| Ciphertext copied to another tenant/field | Tenant, record kind, path, and schema are AEAD associated data |
| Database or backup dump is exposed | Classified fields are ciphertext; key material is outside the database |
| Key is missing, revoked, or envelope is tampered | Decryption fails closed and emits metadata-only audit evidence |
| PII leaks through logs/metrics/errors | Structured redaction and generic error messages; no plaintext in dimensions |
| Operator needs a raw field | Time-bounded, case-bound audit.read.pii decision is itself audited |

## Rollout and acceptance evidence

Implement in separate changes so the policy can be reviewed independently:

1. Add immutable principal/purpose types and route-purpose mapping; test
   wrong-tenant, wrong-role, missing-purpose, unknown-purpose, incomplete
   startup registry, spoofed-header, and verifier failure cases.
2. Add field classification and a local fake FieldEncryptor; test nested
   SQLite persistence without plaintext, successful authorized reads, denied
   reads, producer-schema rejection, tamper detection, malformed/unknown
   envelopes, unknown algorithms, and associated-data replay across tenant,
   record kind, field path, and schema-version changes.
3. Add the approved KV/KMS adapter and Postgres parity tests. Do not make a
   local fake key provider the production default.
4. Add rotation, revocation, retention, rollback, and export verification.
5. Migrate existing audit/analytics plaintext under a tested
   discover-classify-encrypt-verify workflow, including legal holds and
   rollback evidence.
6. Attach exact current-head security, dependency, SAST, and review evidence
   before marking the ADR implemented.

The ADR can move from proposed to accepted only when all of the following
are true:

* an unauthorized principal cannot obtain a classified field;
* an authorized principal receives the field only for the matching purpose;
* SQLite/Postgres exports contain no plaintext classified value;
* tampering, missing keys, revoked versions, and malformed envelopes fail
  closed;
* rotation preserves authorized reads and deletion/retention behavior;
* the access-decision audit contains no raw PII or bearer material.

## Research grounding

* Yang, N., Barringer, H., & Zhang, N. (2007). A purpose-based access
  control model. In *Proceedings of the 3rd International Symposium on
  Information Assurance and Security (IAS 2007)*. IEEE.
  https://doi.org/10.1109/IAS.2007.29. The model formalizes purpose as a
  policy input rather than treating role membership as a complete privacy
  decision; that is why admin is not an implicit raw-PII purpose here.
* Popa, R. A., Redfield, C. M. S., Zeldovich, N., & Balakrishnan, H. (2011).
  CryptDB: Protecting confidentiality with encrypted query processing. In
  *Proceedings of the 23rd ACM Symposium on Operating Systems Principles*
  (pp. 85–100). ACM. https://doi.org/10.1145/2043556.2043566. It demonstrates
  that encrypted database operations involve measurable leakage and
  performance trade-offs; this design therefore refuses to add
  deterministic/searchable encryption without a separate leakage review.
* National Institute of Standards and Technology. (2020). *Recommendation
  for key management: Part 1—General (Revision 5)* (NIST Special Publication
  800-57, Part 1, Revision 5). https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final.
  Its key-lifecycle guidance grounds versioning, protection, rotation,
  revocation, and retention requirements in this ADR.

These sources are cited and linked rather than vendored: the purpose-model
and CryptDB publication licenses/redistribution terms are not established in
this repository, while the implementation must not copy source text.

## More information

* docs/planning/adrs/0003-keyverse-authentication-boundary.md
* docs/planning/adrs/0010-pii-audit-not-mask.md
* docs/kv-credentials.md
* conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md
