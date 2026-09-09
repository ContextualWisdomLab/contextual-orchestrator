# Durable workflow origin identity

The accepted-request ledger and completed workflow records previously had no
durable join. At base c7345670, real HTTP route, conduct and streamed route
requests could not match their persisted outcome to the trusted request ID.

The shared workflow replacement seam now records the trusted HTTP identity on
first creation and preserves it on replacement. Explicit state restoration
retains stored identity instead of attributing history to the loading context.
Non-HTTP runs remain valid without an ID. Cache hits create separate outcome
records with their existing cache-hit classification; the earlier run's origin
is unchanged. This does not make reused output a new provider execution.

The regression also exposed that stream_route never saved its completed run.
It now uses the same synchronous workflow store path as run/conduct. A failed
save emits the existing terminal SSE error, retains the admission and does not
rewrite an earlier initial-decision acknowledgement. As in run/conduct, the
in-memory run and budget update precede storage: memory is not durable proof,
and no atomic memory/database transaction is claimed. Consumers must reconcile
against persisted records rather than count the in-memory run as stored.

Reproduction prerequisite: the unchanged native extension built at base
`c7345670e08f029ad3aa5dd1133037bb4b451d9b` is installed in the existing isolated
Python 3.14 environment below. From `/tmp/co-outcome-request-link-20260909`, run:

```sh
/tmp/co-receipt-wheel-install-20260909/bin/python -c 'import contextual_orchestrator; contextual_orchestrator.__path__.append("/tmp/co-receipt-wheel-install-20260909/lib/python3.14/site-packages/contextual_orchestrator"); import pytest; raise SystemExit(pytest.main(["tests/test_workflow_request_link.py", "tests/test_persistence.py", "tests/test_stream_error_identity.py", "-q"]))'
```

This explicitly loads successor Python source and the unchanged base native
extension. The namespace append is test-only; it does not install the successor
or establish wheel/release acceptance. Preserve that environment unchanged.
The three-file command passed 34 tests in 9.36 seconds. A final linkage-only
run after adding the in-memory failure-state assertion passed 10 in 5.43 seconds.
The independent original HTTP probe also confirmed one admission joins one
durably stored route outcome. Initial four cases failed; subsequent HTTP enabled/disabled,
cache, reload, persistence and SSE regressions passed. Tests use controlled
provider output and establish identity, not independently adjudicated accuracy.
The request may map to multiple workflow outcomes; it is not a one-to-one join
contract for every API. Detached background execution without propagated HTTP
context remains unlinked, rather than guessed from the current thread. Explicit
batch-parent/item linkage and crash recovery after an in-memory-only update
remain outside this bounded repair.
