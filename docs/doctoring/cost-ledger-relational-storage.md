# Cost-ledger relational-storage doctoring record

## Customer-visible gap

The SQL cost ledger duplicated account, service, team, group, and company
attributes in every usage fact. A buyer could receive correct totals while
the database still lacked a reliable relational integrity boundary.

## Change

Execution identity remains on `llm_usage_records`. Descriptive attribution is
now stored in `cost_attribution_values` and linked by
`usage_record_attributions`. `SqlLedgerStore.query()` pivots those normalized
rows back into the existing response fields, so current API clients do not
need a migration.

The store migrates the previous flattened table under an explicit legacy name,
copies each fact and its relational dimensions, and drops the temporary table
only after all rows are inserted. A failed or ambiguous migration raises
without publishing a partial ledger.

Legacy nullable or empty attribution values are normalized to the stable
`unattributed` dimension before insertion into the new `NOT NULL` tables, so
older ledgers remain openable without inventing customer ownership.

SQLite connections enable foreign-key enforcement before schema work begins,
and the dimension catalog is seeded inside the migration transaction before
child rows are inserted. Deleting a usage fact therefore cascades its
attribution links without weakening migration integrity.

SQLite uses `PRAGMA table_info`; PostgreSQL uses `information_schema.columns`
from the first metadata query. The driver branch is deliberate because a
failed SQLite probe would abort a PostgreSQL transaction before fallback.

## Verification

The focused cost-ledger, router, agent-pool, persistence, and naming suites
passed 48 tests; the full repository suite passed 1449 tests in 549.55 seconds.
The normalized storage, migration, foreign-key cascade, and PostgreSQL-style
metadata tests are included in `tests/test_cost_ledger.py`; compileall and
`git diff --check` passed.

## References (APA 7)

Codd, E. F. (1970). A relational model of data for large shared data banks.
*Communications of the ACM, 13*(6), 377–387.
https://doi.org/10.1145/362384.362685

International Organization for Standardization. (2015). *Information
technology—Metadata registries (MDR)—Part 5: Naming principles*
(ISO/IEC 11179-5:2015). https://www.iso.org/standard/60341.html
