# ADR-0004: KV credential registry and bootstrap-only environment

## Status

`implemented_on_protected_main`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Ambient request-time environment lookup makes credential source and rotation
unclear and spreads secret authority across the process (OWASP Foundation,
n.d.-a; National Institute of Standards and Technology, 2022). The product
needs one auditable retrieval seam that works offline and with encrypted
production storage.

Org guidance is explicit: runtime config and provider secrets are resolved
from a KV / credential registry. Environment is only transport into the KV,
never the runtime source. The reference pattern is a pgcrypto-encrypted
Postgres registry (`get_credential(name)`).

## Considered alternatives

- Read provider keys with `os.getenv` on every request: rejected.
- Require one external secret product: conflicts with standalone operation.
- Put secrets in agent JSON: rejected because configuration becomes secret
  data.
- Pluggable KV registry with explicit bootstrap: selected.

## Decision

`ModelAgent` stores a credential name. `get_credential` resolves its value
from an in-memory development backend or a pgcrypto-encrypted Postgres
backend. Environment variables may select, connect, or unlock the KV and may
feed a one-shot `register-credential` CLI, but runtime provider execution does
not use ambient environment fallback.

The legacy `api_key_env` field is accepted as a **credential name**, not as an
environment variable to read.

## Consequences

Mock and offline tests need no secret. Production deployment must operate and
back up the credential registry and protect its passphrase.

## Failure and recovery

Missing or unavailable credentials fail closed before provider egress. Rotate
by revoking at the provider, updating the KV, and verifying stale processes
cannot use the old value.

## Security, privacy, and governance impact

Secret values stay out of agent files, prompts, traces, logs, and telemetry
(International Organization for Standardization, 2022; OWASP Foundation,
n.d.-a). Least-privilege database roles, encryption keys, rotation, and audit
are deployment obligations. This ADR does not claim a managed KMS.

## Compatibility and migration

Existing agent JSON remains readable. Migrate secret values into the KV before
removing old environment injection. Do not expose the old value through a
compatibility log or response.

## Verification and acceptance

Tests cover mock bypass, missing credentials, legacy-name behavior, backend
selection, stdin bootstrap, no ambient fallback, and redacted errors. See
[docs/kv-credentials.md](../kv-credentials.md).

## Rollback and supersession

Rollback selects a previous KV backend, never raw request-time environment
lookup. A dedicated secret manager may supersede Postgres behind the same
seam.

## References

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

International Organization for Standardization. (2022). *Information
security, cybersecurity and privacy protection — Information security
management systems — Requirements* (ISO/IEC 27001:2022).
https://www.iso.org/standard/27001

OWASP Foundation. (n.d.-a). *Secrets management cheat sheet*. Retrieved
August 17, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

See also [docs/REFERENCES.md](../REFERENCES.md).
