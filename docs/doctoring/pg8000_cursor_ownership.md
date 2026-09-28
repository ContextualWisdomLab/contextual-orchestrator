# pg8000 cursor ownership

## Cause

`connect_pg8000` returns a pg8000 1.31.5 DB-API connection. That connection
implements a context manager and closes its socket on exit. The cursor
implements `close()` and does not implement `__enter__` or `__exit__`.
Credential storage, catalog persistence, atomic registration, and credential
rollback all used `with connection.cursor()`. A real cursor raises
`TypeError` before the SQL runs. Cursor doubles that invented the context
manager protocol hid the failure.

The installed wheel in this worktree reports `pg8000` 1.31.5,
`Cursor.__enter__` absent, `Cursor.close` present, and `Connection.__enter__`
present.

## Repair

Twelve cursor scopes use stdlib `contextlib.closing`. The scopes are the four
credential statements, six catalog statements, atomic provider registration,
and provider-credential rollback. Connection scopes and explicit write commits
stay as they were. No pool, retry policy, or driver wrapper was added.
[Python closing contract](https://docs.python.org/3/library/contextlib.html#contextlib.closing).

Draft #1301 repaired eleven of these scopes on an older base and did not
include rollback in `provider_catalog_bootstrap`. This owner branch now carries
all twelve.

## Evidence

Against unmodified production code, after the test doubles dropped the invented
context manager, the focused files failed 14 tests and passed 102 (exit 1).
Each failure was `TypeError` at a `with connection.cursor()` site, including
credential rollback. After `contextlib.closing`, the same files passed 116
tests (exit 0) with plugin autoload disabled.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_credentials_backends.py \
  tests/test_provider_bootstrap_boundaries.py \
  tests/test_provider_catalog_bootstrap_boundaries.py \
  tests/test_provider_catalog_store.py \
  tests/test_provider_catalog_store_boundaries.py
```

The success and failure credential regressions keep the original exception
object and require `cursor.close()`. This run did not start a PostgreSQL
container. Podman machine `podman-machine-default` is stopped at 4GiB, and the
host was already short of free memory. Draft #1301 records a separate
disposable PostgreSQL 18.4 receipt for the earlier eleven scopes. That receipt
is not repeated here and does not cover this head. TLS, release licensing,
full-suite hosted checks, and immutable release remain separate acceptance
work.

## Strix on the previous head

Required Strix job `108841178157` on head `1ceba948` completed with zero
exploitable vulnerabilities, then failed closed because the report did not
identify a changed source file. That is the scan-evidence contract, not a
vulnerability finding in the driver change.
