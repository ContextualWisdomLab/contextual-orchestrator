# ADR-0013: Descriptive database naming and evidence-driven migration

## Status

`accepted_architecture`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

The repository naming contract requires descriptive two-or-more-word
`snake_case` for configurable, API, and database objects
([docs/code_conventions.md](../code_conventions.md);
[docs/database_conventions.md](../database_conventions.md)). Paper role
values (`thinker`, `worker`, `verifier`, `synthesizer`) are deliberate
exceptions because they are source terminology from Xu et al. (2026).

Renaming or applying target DDL without compatibility evidence risks data
loss and misleading architecture claims (National Institute of Standards
and Technology, 2022).

## Considered alternatives

- Silently call a target SQL file current: inaccurate.
- Rename legacy tables in place: breaks existing stores and rollback.
- Exempt all database objects from naming rules: removes useful
  consistency.
- Document exceptions and migrate through expand/backfill/verify/contract:
  selected.

## Decision

New owned database identifiers use descriptive two-or-more-word snake_case,
except externally fixed standards and the paper role values. Legacy or
generic names remain readable until a migration introduces a descriptive
replacement, backfills idempotently, verifies counts and content, supports a
bounded compatibility window, and contracts only after rollback is safe.

Actual, external, in-memory, active-PR, and target schemas remain separately
labeled.

## Consequences

Legacy names may persist temporarily, but no new ambiguous one-word objects
are added. Documentation reflects physical truth and migrations cost more
upfront.

## Failure and recovery

Any schema, backfill, reconciliation, or reader-compatibility failure stops
before contract. Recovery returns reads and writes to the last compatible
schema, restores a verified backup if necessary, and records incomplete rows
explicitly.

## Security, privacy, and governance impact

Migrations preserve least-privilege roles, encryption, retention, deletion,
tenant boundaries, and audit identity (International Organization for
Standardization, 2022). Backfill logs never print payloads or credentials.

## Compatibility and migration

Use expand, dual read/write where needed, idempotent backfill,
reconciliation, switch, observation, and contract. Each supported prior
version has a tested reader or an explicit upgrade boundary.

## Verification and acceptance

`tests/test_conventions.py` checks example agent ids and naming helpers.
Migration tests, when added, must introspect physical schemas and prove
rollback before contract.

## Rollback and supersession

Rollback is mandatory until contract. A later ADR may remove the
compatibility path only after retention and deployed-version evidence show
it is safe.

## References

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026).
*TRINITY: An evolved LLM coordinator* (arXiv:2512.04695, Version 3)
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04695

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

International Organization for Standardization. (2022). *Information
security, cybersecurity and privacy protection — Information security
management systems — Requirements* (ISO/IEC 27001:2022).
https://www.iso.org/standard/27001

See also [docs/REFERENCES.md](../REFERENCES.md).
