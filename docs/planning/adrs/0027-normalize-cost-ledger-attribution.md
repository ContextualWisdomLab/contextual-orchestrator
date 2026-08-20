# ADR 0027: Normalize Cost-Ledger Attribution

- Status: Accepted
- Date: 2026-08-21
- Decision owners: contextual-orchestrator maintainers

## Context

`llm_usage_records` repeated account, service, team, group, and company values
on every request row. Repetition made attribution updates expensive and left
the buyer-facing ledger vulnerable to inconsistent dimension values.

## Decision

Keep execution evidence (`provider_name` and `model_name`) on the usage fact
row. Store descriptive attribution values once in
`cost_attribution_values`, then link each usage row to its five descriptive
dimensions through `usage_record_attributions`. The composite foreign key
ensures a link points to a declared dimension value, while the composite
primary key allows at most one value per dimension for a usage record.

The SQL query surface remains backward compatible: `SqlLedgerStore.query()`
continues returning the established flattened dictionary and rollups continue
to use the same dimension names. Existing flattened SQLite ledger tables are
migrated transactionally; ambiguous or incompatible schemas fail closed.

## Consequences

- SQL consumers can inspect and constrain attribution values without parsing a
  repeated fact row.
- Existing reports and HTTP responses retain their public field names.
- A first open of an existing ledger performs a one-time migration.
- Pricing remains in the existing KV-backed price book; this ADR does not
  redesign provider price governance.

## Evidence and next action

Run `pytest tests/test_cost_ledger.py tests/test_cost_router.py` before
deploying a SQL ledger. The tests prove normalized inserts, legacy migration,
all query windows, Python DB-API parameter styles, cost rollups, and the
unchanged flattened query contract.

## Research basis (APA 7)

Codd, E. F. (1970). A relational model of data for large shared data banks.
*Communications of the ACM, 13*(6), 377–387.
https://doi.org/10.1145/362384.362685

International Organization for Standardization. (2015). *Information
technology—Metadata registries (MDR)—Part 5: Naming principles*
(ISO/IEC 11179-5:2015). https://www.iso.org/standard/60341.html
