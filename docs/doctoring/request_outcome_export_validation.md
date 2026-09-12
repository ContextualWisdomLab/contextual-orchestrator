# Retained outcome export validation

## Candidate and ownership

PR #1138 remains the export owner. Local merge base
`d1a080d7bd9de4e37aa72a7f98f9414abc0362fc` preserves the existing export delta
and normally merges research head `de21ffd42733d6115800b33c4e84b3626a33f758`.
The prior 92-open-PR audit narrowed 37 overlapping-file candidates to #1138's
export implementation and #1107's inherited receipt contract; the other 35 did
not alter the target exporter/schema. This is target ownership evidence, not
whole-stack merge approval.
The measurements below concern the source and test tree committed as
`7ebf577535139c6655a1b8d360682511defc22ba`, tested and visually inspected before
commit. They do not establish a released artifact or hosted acceptance.

## Contract and regression evidence

The admin export must refuse disabled measurements with HTTP 503, after
authorization and before querying the journal. An empty HTTP 200 response must
not imply that an unmeasured cohort contains no requests.

Pagination joins admission, initial decision, and final receipt at one fixed
high-water sequence. A 257-admission unit test spans pages of 200 and 57 and
excludes an acknowledgement appended after the first page. Canonical provenance
is projected without inventing eligibility scores or timing values. An initial
phase establishes `acknowledgement_unobserved` only with matching identity,
`selected` status, an unsigned 64-bit selection time, and no acknowledgement.
Malformed times become null and remain countable. These are synthetic unit
records, not empirical accuracy or latency measurements.

Independent review reproduced nine malformed-phase cases that failed before
the final validation guards: false initial status, missing/boolean/negative/
overflow selection times, premature initial acknowledgement, and boolean/
negative/overflow final acknowledgement. After repair, the focused group passed
62 tests in 2.43 seconds with process exit 0 and warnings treated as errors:

```sh
.venv/bin/python -m pytest tests/test_cost_request_cleanup.py tests/test_paginated_decision_provenance.py tests/test_request_outcome_export.py -q -W error --tb=short
```

## Reproducible environment

Both the detached parent audit and candidate use CPython 3.14.6, Rust 1.97.1,
the checked-in dependency lock, and an actual native extension. No test double,
system installation, environment-path override, warning filter, or forced
garbage collection is used for acceptance.

```sh
uv sync --locked --offline --extra api --extra db --extra queue --group dev --group native-build
uv run --no-sync maturin develop --locked --release --features pyo3/extension-module --manifest-path rust/decision_receipt/Cargo.toml
```

Native build output in the source package is generated evidence, not a source
file to commit. Editable native success is not isolated wheel-install proof.

## Resource-warning root causes and inherited failures

The shared HTTP helper now closes `HTTPError` responses even when JSON parsing
raises. Two focused regressions failed before this change and pass afterward.
PR #982 at `20783edd7b39ff6439e9ea463f17d2e274b0ade8` also touches the helper's
test module but does not alter the helper; its inserted test must be preserved.

Allocation tracing found two additional leaks in this export's migration
fixtures. SQLite connection context managers finish transactions but do not
close connections. Wrapping these two fixtures with `contextlib.closing` while
retaining their transaction contexts changed the 53-test process from exit 1
at shutdown to exit 0. No production connection lifecycle was altered.

The six-module expansion initially produced 94 passes and 21 failures. A
receipt-only run produced two failures at different collection points. These
locations do not identify allocation owners: collection can expose an earlier
test's leaked resource.

The 23-node union was therefore compared one node per fresh process on parent
and candidate, with identical flags and independently built native extensions.
All 19 cost-review nodes and the two streaming initial-decision nodes failed
on both trees. The legacy-index and embedding-failover nodes passed on both.
No candidate-only exit regression appeared in those 46 processes. The raw local
audit is `/tmp/co-export-node-comparison-20260912.jsonl`; the runner is
`/tmp/co-export-node-comparison-20260912.py`. This comparison predates the final
nine-case projection guard, whose focused regression is recorded above.

The inherited allocation owners were separate from export projection:

- `tests/test_cost_review_server.py`: test cleanup calls `server.shutdown()`
  without `server.server_close()`. Listener sockets remained open in the first
  comparison candidate even after its HTTPError helper repair.
- `tests/test_decision_receipts.py`: `inspect_committed_decision` opens independent
  SQLite connections using only transaction contexts. Allocation tracing points
  to that helper, not the later node where collection reports the warning.

After exact-hunk ownership checks, the coordinator authorized two test-only root
repairs. The open-PR file audit found only parent #1107 for the SQLite helper and
#982 for the cost-review module. #982 inserts a test at the later batch section;
it changes neither the builder nor the cleanup fixture region. The SQLite
inspection helper now uses `closing` with its transaction context. One module
fixture registers every real server's `server_close` in an `ExitStack`, covering
both `_serve` and direct construction without per-test patches. Existing tests
still stop their serving loops. No production builder behavior is replaced.

With both root repairs and the final malformed-phase guards, all six modules
passed **124 tests in 4.85 seconds**, process exit 0, under `-W error`:

```sh
.venv/bin/python -m pytest tests/test_cost_request_cleanup.py tests/test_paginated_decision_provenance.py tests/test_request_outcome_export.py tests/test_decision_receipts.py tests/test_request_outcome_associations_1114.py tests/test_cost_review_server.py -q -W error --tb=short
```

The final 23-node independent-process rerun passed all 23 nodes, every process
exit 0 (`/tmp/co-export-final-nodes-20260912.jsonl`). The autouse fixture applies
under pytest; this evidence does not cover the module's direct-script runner.

## Fresh wheel installation

Offline `uv build --wheel` and locked `maturin build --release` produced disjoint
core/native wheels; the checked-in manifest verifier passed. SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| Core 0.2.0 | `456b8e53b075cd6c4654eda23c580999a911bc1f3ff7f0e98fcbe85c73f769bd` |
| Native 0.1.0, macOS arm64 abi3 | `a2d9456d11ed7032b76a15c2e5562b202c6aad9521285b312073c9dff5b6d55b` |

Fresh environment `/tmp/co-export-wheel-proof.cMPOol/isolated_env` received the
locked dependencies and both wheels noneditably, without dependency resolution
during wheel installation. Both import origins were asserted under its
site-packages. Unmodified copies of the six test modules and their batch helper
ran outside the checkout using `python -I -m pytest --noconftest ... -q -W error`:
**124 passed in 50.30 seconds, exit 0**. This includes the focused 62 cases and
the HTTP/export subset. It proves this local macOS artifact matrix, not Linux
hosted acceptance or a public release.

Independent final diff review found the prior malformed-phase findings repaired
and no further blocking finding. Hosted checks, current-head independent
approval, deployment, ingress reconciliation, and customer KPI measurements
remain open.

## Rendered inspection

The actual in-app browser rendered the candidate at
`http://127.0.0.1:18441` in English/default at a requested 1265 × 712 viewport.
The operator directly inspected successive screenshots of `/runbook`, the
changed sections of `/agents`, `/claude`, `/gap`, and the complete `/diff`,
including both new test files. Screenshot evidence is attached to task
`01a06c7e-d687-7352-90fb-adbea73e46b4` (browser tab 35). Body text, source wrapping,
long hashes, headings, and vertical scrolling remained readable with no content
overlap or horizontal clipping observed. The export guidance initially appeared
under an unrelated handoff heading; a dedicated heading was added and the
rendered section re-inspected. This checks changed documentation/source
rendering only, not the product's full locale, responsive, or interaction matrix.
