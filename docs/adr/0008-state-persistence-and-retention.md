# ADR-0008: Explicit state persistence and retention authority

## Status

`accepted_architecture` — in-memory defaults and opt-in SQLite persistence are
`implemented_on_protected_main`; production retention, tenancy, encryption, and
migrations remain incomplete.

## Context and decision drivers

Standalone operation benefits from zero-infrastructure defaults, while audits
and restart recovery may require durable state. Workflow payloads can contain
prompts, answers, and PII, so silently enabling persistence would create
security, privacy, recovery, and records-management obligations.

## Considered alternatives

- always persist to a database: durable but violates the standalone and
  data-minimization defaults;
- memory only: simple but cannot support requested restart evidence;
- persist only telemetry: insufficient for authorized workflow recovery;
- default to memory and enable each store explicitly with operator authority:
  selected.

## Decision

Process memory is the default. SQLite state and agent overlays, the SQL cost
ledger, and the Postgres credential backend are separate opt-in adapters with
separate ownership. Enabling payload persistence requires an operator-defined
purpose, audience, encryption, retention, deletion, backup, residency, and
recovery policy. Generic runtime JSON is not presented as the normalized target.

## Consequences

A default restart loses ephemeral state by design. Durable deployments must do
more operational work, but can choose the minimum store needed and can reason
about its data classification.

## Failure and recovery

Store failure is visible and cannot be converted into a claim of durable
evidence. Operators preserve a failed file read-only, restore a verified backup
or initialize an explicitly new store, reconcile gaps, and run restart tests.

## Security, privacy, and governance impact

Generic `records.payload` may contain sensitive content and currently lacks
field encryption, automatic pruning, tenant partitioning, and subject-rights
workflows. Those gaps block production durability claims unless the host
supplies compensating controls.

## Compatibility and migration

Existing in-memory and SQLite deployments remain supported. Any move to the
normalized target uses expand, backfill, verify, switch, and contract phases
with reader compatibility and rollback.

## Verification and acceptance

Tests cover disabled-by-default behavior, restart recovery, schema identity,
parameter binding, bounds, corruption/unavailability, retention hooks, backup
restore, and reconciliation between generic and normalized representations.

## Rollback and supersession

Disable the adapter only after preserving or deliberately disposing of data
under policy. Supersession requires a data migration, dual-read/write boundary,
reconciliation proof, and tested rollback.

## References

NIST (2022, 2024b) and ISO/IEC 27001:2022. See
[the reference index](../REFERENCES.md).
