# ADR 0025: Use descriptive multi-word database object names

- Status: Accepted
- Date: 2026-08-21
- Decision owners: contextual-orchestrator maintainers

## Decision

Application-owned database tables, indexes, views, sequences, and constraints
must use at least two descriptive words in `snake_case`. The runtime state table
is therefore `orchestration_records`, and its query index is
`orchestration_records_kind_seq`. The previous single-word `records` table is
renamed automatically when an existing SQLite state database is opened.

If both the legacy and current state tables exist, startup fails closed rather
than guessing which rows are authoritative. This protects buyer audit history
from silent duplication or loss.

## Consequences

Existing state databases migrate in place through SQLite's transactional rename
operation. New databases never create the single-word object. The public
orchestrator API and payload names remain unchanged; only application-owned
database identifiers are corrected.

## Evidence and next action

Run `pytest tests/test_persistence.py` before deploying a state database. The
migration test proves legacy rows survive, the schema test proves the new names,
and the dual-schema test proves ambiguous state is rejected.

## APA 7 reference

International Organization for Standardization. (2015). *Information
technology—Metadata registries (MDR)—Part 5: Naming principles* (ISO/IEC
11179-5:2015). https://www.iso.org/standard/60341.html
