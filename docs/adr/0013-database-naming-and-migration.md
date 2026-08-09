# ADR-0013: Descriptive database naming and evidence-driven migration

## Status

`accepted_architecture`

## Context and decision drivers

The repository naming contract requires descriptive two-or-more-word
snake_case. Protected main also has a legacy one-word SQLite table, `records`,
while [`database_design.sql`](../database_design.sql) describes a normalized target that runtime does
not create. Renaming or applying target DDL without compatibility evidence risks
data loss and misleading architecture claims.

## Considered alternatives

- silently call the target SQL current: inaccurate;
- rename `records` in place: breaks existing stores and rollback;
- exempt all database objects from naming rules: removes useful consistency;
- document the exception and migrate through expand/backfill/verify/contract:
  selected.

## Decision

New owned database identifiers use descriptive two-or-more-word snake_case,
except externally fixed standards. `records` is explicit technical debt and
remains readable until a migration introduces a descriptive replacement such as
`runtime_records`, backfills idempotently, verifies counts/content, supports a
bounded compatibility window, and contracts only after rollback is safe. Actual,
external, in-memory, active-PR, and target schemas remain separately labeled.

## Consequences

The legacy name persists temporarily, but no new ambiguous one-word objects are
added. Documentation reflects physical truth and migrations cost more upfront.

## Failure and recovery

Any schema, backfill, reconciliation, or reader-compatibility failure stops
before contract. Recovery returns reads/writes to the last compatible schema,
restores a verified backup if necessary, and records incomplete rows explicitly.

## Security, privacy, and governance impact

Migrations preserve least-privilege roles, encryption, retention, deletion,
tenant boundaries, and audit identity. Backfill logs never print payloads or
credentials.

## Compatibility and migration

Use expand, dual read/write where needed, idempotent backfill, reconciliation,
switch, observation, and contract. Each supported prior version has a tested
reader or an explicit upgrade boundary.

## Verification and acceptance

Tests introspect physical schemas, enforce new-name rules, migrate realistic old
stores, verify row/content parity and indexes, exercise interruption/resume,
restore backups, and prove rollback before contract.

## Rollback and supersession

Rollback is mandatory until contract. A later ADR may remove the compatibility
path only after retention and deployed-version evidence show it is safe.

## References

NIST SP 800-218 and ISO/IEC 27001:2022. See
[the reference index](../REFERENCES.md).
