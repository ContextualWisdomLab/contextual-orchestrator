# pg8000 cursor ownership repair (2026-09-27)

## Scope and cause

Owner PR #1225 at `594ea2c825742bf186454f83a89f39bc7655da58`
returns a real pg8000 DB-API connection. Its connection supports a context
manager and closes physically on exit; its cursor supports `close()` but
neither `__enter__` nor `__exit__`. Existing context-manager cursor doubles
hid an immediate TypeError in credentials, catalog persistence, and atomic
credential registration. The exact downloaded pg8000 1.31.5 wheel was
verified against the owner's hash lock before execution.

All eleven cursor scopes now use stdlib `contextlib.closing`. No driver
wrapper, SQLAlchemy pool, retry, or transaction policy was introduced.
Connection scopes and explicit write commits are retained. Test doubles now
implement the actual cursor close protocol. Two regression cases assert
closure after success and preserve the query exception object after failure.
[Python closing contract](https://docs.python.org/3/library/contextlib.html#contextlib.closing).

## Evidence

- RED: the two new credential regressions against unmodified owner production
  source failed (exit 1); GREEN: the credential file passed 14 tests (exit 0).
- The five affected existing test files passed 110 tests before adding the
  two regressions. The final five-file run passed 112 tests (exit 0). The QA environment emits an existing unknown
  `asyncio_default_fixture_loop_scope` configuration warning; this is not
  strict-warning or complete-suite acceptance.
- Real PostgreSQL 18.4, existing image
  `sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636`,
  was started in a task-owned disposable container with a dynamically assigned
  loopback-only port. Other containers and databases were untouched.
- Real encrypted credential set/get/delete, atomic two-credential registration,
  catalog write/read, explicit committed DDL, and uncommitted INSERT rollback
  after a sentinel exception all passed. The original exception identity and
  pg8000 physical socket closure were asserted; a separate observer found zero
  other test-owned sessions in `pg_stat_activity`. Process exit was 0.
- Only the owned container
  `4e50dbf9b0511e85f467ad84200252ef377f59a802ce576f55770d1d69433be3`
  was stopped; `--rm` removed it and a name-filtered readback was empty.

Reproduce the isolated regression with the owner's project dependencies:

```sh
uv run --locked --extra test --extra db python -m pytest -q \
  tests/test_credentials_backends.py \
  -k closes_dbapi_cursor_without_context_protocol
```

The live receipt used exact changed source modules and pinned driver wheels
with an existing QA interpreter, not an installed released core/native pair.
TLS verification, release container licensing, full-suite hosted checks,
protected owner delivery, and immutable release remain separate acceptance
requirements. A local PostgreSQL test image is not a cleared release artifact.
