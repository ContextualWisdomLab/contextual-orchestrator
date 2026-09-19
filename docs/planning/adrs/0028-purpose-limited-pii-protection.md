---
id: "0028"
title: "Protect marked PII with purpose-limited access and field encryption"
status: accepted
proposed_date: "2026-08-21"
accepted_date: "2026-08-21"
deciders:
  - "repository maintainer"
consulted:
  - "governance-risk-compliance (org PII policy owner)"
informed:
  - "downstream consumers (naruon, gyeot, scopeweave)"
affected_components:
  - "contextual_orchestrator/pii_protection.py"
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "tests/test_pii_protection.py"
related:
  - path: "docs/planning/adrs/0010-pii-audit-not-mask.md"
    relation: follows
---

# Protect marked PII with purpose-limited access and field encryption

## Context

ADR 0010 correctly stopped destructive email/PII masking, but left its two
explicit follow-ups open: the server had no purpose-and-role policy for raw
content, and stored event fields had no encryption boundary. The gateway must
preserve usable content for authorized consumers without making every caller a
raw-data reader.

## Decision

Use the existing bearer roles as the authenticated role and assign fixed,
route-owned purposes:

| Role | Purpose | Surface |
|---|---|---|
| `inference` | `message_delivery` | OpenAI-compatible inference responses |
| `admin` | `operator_read` | Aggregate/operator endpoints |
| `admin` | `audit_replay` | Admin state and workflow/access/evaluation traces |

Denied authorization results and successful raw-PII replay decisions are
recorded without client IPs, tokens, or raw content. Routine successful
inference/operator traffic keeps using the existing analytics path. The route
chooses the purpose; a caller cannot escalate by declaring a different purpose
in request data. Invalid role-purpose combinations fail closed.

Governance audit records commit synchronously with their bounded retention;
only explicitly non-durable authorization denials and routine analytics use
the best-effort background stream.

Callers that place personal data in audit or analytics details must declare the
top-level fields through `pii_fields`. Those fields are encrypted with
AES-256-GCM using a 32-byte key resolved from the existing KV credential
registry (`CONTEXTUAL_ORCHESTRATOR_PII_ENCRYPTION_KEY` by default). Generated
key bytes must use an explicit `base64:` or `hex:` encoding; an operator
passphrase must use `passphrase:<base64-salt>:<passphrase>` and is derived
with memory-hard scrypt. The salt must be a generated, unique 16-byte-or-longer
value retained with the passphrase in the KV credential.
Unprefixed raw 32-byte strings are rejected so a human passphrase cannot be
mistaken for uniformly random key material. Ciphertext,
nonce, algorithm, version, and key name are stored; the plaintext field is not.
Missing/invalid keys, malformed envelopes, missing fields, and authentication
failures raise an error rather than storing or returning plaintext. Unmarked
fields keep the existing behavior so the gateway does not guess at PII or mask
usable content.

Version 2 binds the AEAD associated data to a canonical JSON array containing
the event context, key name, and field label, rather than joining these values
with a delimiter. This prevents a key name and field label containing colons
from being recombined into the same authenticated context. Safe version 1
records remain readable for migration; a version 1 key name or field label with
a colon is rejected because its legacy context is ambiguous.

## Consequences

* The old OpenAI-compatible request and response shapes remain unchanged.
* Direct Python callers must pass `pii_fields` when recording PII-bearing
  events; this explicit declaration is the trust boundary and avoids an
  unreliable PII detector.
* Authorized admin replay decrypts protected audit fields; ordinary internal
  reads see the ciphertext envelope.
* Key rotation is represented by the stored key name; old keys must remain in
  the KV registry until their protected records expire or are re-encrypted.
* Changing a KV key name or passphrase/salt rotates the derived key; old
  records therefore require the prior KV credential during replay.

## Evidence

* OWASP. (n.d.). *Cryptographic storage cheat sheet*.
  https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html
* Barker, E. (2020). *Recommendation for key management: Part 1—General*
  (NIST SP 800-57 Pt. 1 Rev. 5). National Institute of Standards and
  Technology. https://doi.org/10.6028/NIST.SP.800-57pt1r5
* Percival, C., & Josefsson, S. (2016). *The scrypt password-based key
  derivation function* (RFC 7914). RFC Editor. https://www.rfc-editor.org/rfc/rfc7914
* Wolf, K., Pallas, F., & Tai, S. (2021). Messaging with purpose limitation—
  Privacy-compliant publish-subscribe systems. arXiv. https://arxiv.org/abs/2110.15150

The cited paper is linked rather than vendored because redistribution rights
for the downloaded copy were not independently established in this run.
