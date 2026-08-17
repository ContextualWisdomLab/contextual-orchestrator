# ADR-0008: Explicit state persistence and retention authority

## Status

`accepted_architecture` — in-memory defaults and opt-in SQLite persistence
(`--state-db`, `--agents-db`) are `implemented_on_protected_main`. Production
retention, tenancy, field encryption, and subject-rights workflows remain
incomplete.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Standalone operation benefits from zero-infrastructure defaults, while audits
and restart recovery may require durable state. Workflow payloads can contain
prompts, answers, and PII, so silently enabling persistence would create
security, privacy, recovery, and records-management obligations
(International Organization for Standardization, 2022; National Institute of
Standards and Technology, 2023).

## Considered alternatives

- Always persist to a database: durable but violates the standalone and
  data-minimization defaults.
- Memory only: simple but cannot support requested restart evidence.
- Persist only telemetry: insufficient for authorized workflow recovery.
- Default to memory and enable each store explicitly with operator
  authority: selected.

## Decision

Process memory is the default. SQLite state and agent overlays, the SQL cost
ledger, and the Postgres credential backend are separate opt-in adapters with
separate ownership. Enabling payload persistence requires an operator-defined
purpose, audience, encryption, retention, deletion, backup, residency, and
recovery policy.

The filesystem is ephemeral in many hosted deployments. Local writes are not
a production system of record.

## Consequences

A default restart loses ephemeral state by design. Durable deployments must
do more operational work, but can choose the minimum store needed and can
reason about its data classification.

## Failure and recovery

Store failure is visible and cannot be converted into a claim of durable
evidence. Operators preserve a failed file read-only, restore a verified
backup or initialize an explicitly new store, reconcile gaps, and run restart
tests.

## Security, privacy, and governance impact

Generic persisted payloads may contain sensitive content. Field encryption,
automatic pruning, tenant partitioning, and subject-rights workflows are
host-owned unless a later ADR ships them here. Those gaps block production
durability claims unless the host supplies compensating controls.

## Compatibility and migration

Existing in-memory and SQLite deployments remain supported. Any move to a
normalized schema uses expand, backfill, verify, switch, and contract phases
with reader compatibility and rollback ([ADR-0013](0013-database-naming-and-migration.md)).

## Verification and acceptance

Tests cover disabled-by-default behavior, restart recovery, schema identity,
parameter binding, bounds, and unavailability.

## Rollback and supersession

Disable the adapter only after preserving or deliberately disposing of data
under policy. Supersession requires a data migration, dual-read/write
boundary, reconciliation proof, and tested rollback.

## References

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

International Organization for Standardization. (2022). *Information
security, cybersecurity and privacy protection — Information security
management systems — Requirements* (ISO/IEC 27001:2022).
https://www.iso.org/standard/27001

See also [docs/REFERENCES.md](../REFERENCES.md).
