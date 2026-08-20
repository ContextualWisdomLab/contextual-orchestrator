# Agent-pool relational-storage doctoring record

## Customer-visible gap

An operator could persist an agent, but the database stored the entire agent
configuration as opaque JSON. This prevented SQL-level inspection of tags and
provider exclusions and made partial integrity checks impossible.

## Change

The persistence layer now uses three normalized SQLite tables:

- `agent_pool` stores one row per agent and scalar configuration.
- `agent_pool_tags` stores one ordered row per tag.
- `agent_pool_provider_exclusions` stores one ordered row per excluded provider.

Legacy JSON rows migrate transactionally. If decoding or schema validation
fails, startup fails closed and the legacy table remains intact.

## Verification

`tests/test_agent_pool_db.py` covers restart persistence, add/patch/remove
behavior, ordered multi-valued attributes, legacy migration, malformed legacy
rollback, and the HTTP worker-agent contract. The focused run on the change
head passed 9 tests; Ruff, compileall, and `git diff --check` also passed.

## References (APA 7)

Codd, E. F. (1970). A relational model of data for large shared data banks.
*Communications of the ACM, 13*(6), 377–387.
https://doi.org/10.1145/362384.362685

International Organization for Standardization. (2015). *Information
technology—Metadata registries (MDR)—Part 5: Naming principles*
(ISO/IEC 11179-5:2015). https://www.iso.org/standard/60341.html
