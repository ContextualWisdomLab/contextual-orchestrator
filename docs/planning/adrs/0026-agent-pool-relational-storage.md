# ADR 0026: Store Agent Pool Attributes in Third-Normal-Form Tables

- Status: Accepted
- Date: 2026-08-21
- Decision owners: contextual-orchestrator maintainers

## Context

The durable agent pool stored each `ModelAgent` as one JSON payload. That made
tags, provider exclusions, and scalar configuration invisible to SQL integrity
checks and made partial updates depend on deserializing the whole document.
The JSON format also made the repository's 3NF requirement unenforceable for a
core operational database.

## Decision

Store scalar agent attributes in `agent_pool`, ordered tags in
`agent_pool_tags`, and ordered provider exclusions in
`agent_pool_provider_exclusions`. Each child row depends on the full composite
key `(agent_id, position)`, and foreign keys prevent orphaned values. Legacy
`agent_pool(agent_id, payload)` databases migrate inside an explicit SQLite
transaction; malformed or ambiguous input rolls back and keeps the original
table available for recovery.

The public `ModelAgent` and admin API contracts remain unchanged. JSON remains
an interchange representation at the API boundary, not a persistence format.

## Consequences

- Operators can query and constrain agent attributes without decoding payloads.
- Ordered tags and exclusions remain round-trip compatible with existing agents.
- A migration is required on first startup for legacy agent-pool databases.
- The cost ledger and PostgreSQL design document still need their own 3NF
  review; this decision closes only the durable agent-pool slice.

## Evidence and next action

Run `pytest tests/test_agent_pool_db.py` before deploying an existing agent
database. The suite proves normalized tables, ordered-attribute round trips,
legacy migration, malformed-input rollback, restart persistence, and HTTP
management behavior.

## Research basis (APA 7)

Codd, E. F. (1970). A relational model of data for large shared data banks.
*Communications of the ACM, 13*(6), 377–387.
https://doi.org/10.1145/362384.362685

International Organization for Standardization. (2015). *Information
technology—Metadata registries (MDR)—Part 5: Naming principles*
(ISO/IEC 11179-5:2015). https://www.iso.org/standard/60341.html
