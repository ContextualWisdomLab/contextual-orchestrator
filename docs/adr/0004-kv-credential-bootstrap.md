# ADR-0004: KV credential registry and bootstrap-only environment

## Status

`implemented_on_protected_main`

## Context and decision drivers

Ambient request-time environment lookup makes credential source and rotation
unclear and spreads secret authority across the process. The product needs one
auditable retrieval seam that works offline and with encrypted production
storage.

## Considered alternatives

- read provider keys with `os.getenv` on every request: rejected;
- require one external secret product: conflicts with standalone operation;
- put secrets in agent JSON: rejected because configuration becomes secret data;
- pluggable KV registry with explicit bootstrap: selected.

## Decision

`ModelAgent` stores a credential name. `get_credential` resolves its value from
an in-memory development backend or pgcrypto-encrypted Postgres backend.
Environment variables may select/connect/unlock the KV and may feed a one-shot
bootstrap CLI, but runtime provider execution does not use ambient environment
fallback.

## Consequences

Mock/offline tests need no secret. Production deployment must operate and back
up the credential registry and protect its passphrase. The legacy
`api_key_env` field is only a credential-name alias.

## Failure and recovery

Missing/unavailable credentials fail closed before provider egress. Rotate by
revoking at the provider, updating KV, and verifying stale processes cannot use
the old value.

## Security, privacy, and governance impact

Secret values stay out of agent files, prompts, traces, logs, and telemetry.
Least-privilege database roles, encryption keys, rotation, and audit are
deployment obligations.

## Compatibility and migration

Existing agent JSON remains readable. Migrate secret values into KV before
removing old environment injection. Do not expose the old value through a
compatibility log or response.

## Verification and acceptance

Tests cover mock bypass, missing credentials, legacy-name behavior, backend
selection, stdin bootstrap, no ambient fallback, encryption SQL, and redacted
errors.

## Rollback and supersession

Rollback selects a previous KV backend, never raw request-time environment
lookup. A dedicated secret manager may supersede Postgres behind the same seam.

## References

NIST SP 800-218 and ISO/IEC 27001:2022; see
[the reference index](../REFERENCES.md).
