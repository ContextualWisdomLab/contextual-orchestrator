# Database Conventions

## Naming

- Every database object name uses lower snake_case.
- Every table, enum, index, constraint, and column name has at least two words.
- Do not use quoted identifiers.
- Primary key columns are resource-specific: `agent_id`, `workflow_run_id`, `audit_event_id`.
- Foreign keys keep the referenced resource name: `workflow_run_id`, `policy_id`.
- Timestamps are `created_at`, `updated_at`, or domain-specific two-word names such as `started_at`.

## Migrations

- Alembic is the production migration tool.
- Every migration has upgrade and downgrade paths.
- Breaking changes use expand/backfill/contract phases.
- Large data changes are batched and monitored.

## Persistence Stack

- PostgreSQL for the primary store.
- SQLAlchemy 2.x ORM mappings for Python services.
- Alembic autogenerate may draft migrations, but humans review object names and downgrade behavior.

