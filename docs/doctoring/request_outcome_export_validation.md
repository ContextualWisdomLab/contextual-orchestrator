# Retained outcome export validation

## Request decision milliseconds, 2026-09-13

Hosted acceptance remains outstanding at documentation head
`cb97ec6615dcbef5d3f97901261a5c3125151bd5`. Run `34708601751` reports all
three Security and Quality jobs skipped. Each job's checked-in condition
excludes draft pull requests; the skip is not evidence of missing secrets or
successful testing. A subsequent run-details lookup returned an explicit API
rate-limit 403. Keep this distinct from authentication and organization-secret
authorization failures. The existing manual workflow trigger can validate a
candidate branch without changing its Draft status, but no such execution is
claimed here. Its run head and terminal job results must be checked separately
from protected PR approval and merge requirements.

The full added section at `cb97ec66`, including the artifact and regression
paragraphs below, was directly inspected in two actual GitHub browser
screenshots at 1265 x 712, English. Text, commands and hashes wrapped readably
without observed overlap or clipping. This supersedes only the follow-up
paragraph inspection pending note below; complete code-diff and product UI
inspection remain outstanding. Screenshots are in task
`01a06c7e-d687-7352-90fb-adbea73e46b4`, browser tab 55.

The additive export field `decision_latency_ms` converts the validated final
receipt's `durable_ack_elapsed_ns` by 1,000,000. The native monotonic clock and
raw nanoseconds remain authoritative; this is JSON presentation, not a new
estimator, timer or routing policy. Invalid, missing, failed and unfinished
acknowledgements remain null. It describes one initial request decision, never
each workflow step or upstream generation. It does not establish correctness,
a complete ingress denominator, or a p95 improvement.

PR #1125's proposed field name is retained as a request-level export contract,
not its unimplemented trace-row claim. This candidate is based on PR #1138 at
`1881ef06ed90ee72eb7209434db366c851cd68dc`; neither predecessor is closed or
claimed fully superseded. Existing export authorization and pagination remain.

Baseline projection tests: 24 passed in 9.35s. Test commit `876c02d0` reproduced
the missing field (10 failed, 14 passed in 1.12s). Independent review then found
that a receipt missing its acknowledgement could inherit a stale admission
value. RED `be35784b` reproduced that defect; `7748e5b1` restricts the source to
the final receipt, fixing the raw nanosecond projection as well. At `39d2dad4`,
strict projection and HTTP export suites passed 61 tests in 2.90s, including an
actual HTTP request, restart, admin export, unit conversion and capacity-failure
null. Provider output is controlled unit evidence, not observed customer data.

Reproduce with the locked environment and native build commands below, using
`uv sync --locked --python 3.12 --extra api --extra db --extra queue --group dev --group native-build`.
Run `uv run --no-sync python -m pytest -q -W error tests/test_paginated_decision_provenance.py tests/test_request_outcome_export.py`.
The first expanded run lacked the native module (29 passed, 1 failed, 30 setup
errors in 9.65s); building the current extension resolved that prerequisite.
Do not reuse another checkout's binary.

Second review RED `7bc5b655` reproduced a missing selection inherited from the
admission (1 failed, 1 passed, 24 deselected in 0.80s). Fix `45cc666f` requires
selection from the final receipt or a validated initial phase; explicit invalid
selection is not replaced. Independent re-review found both provenance findings
resolved, with no further specific defect in the bounded projection delta.

At source `45cc666f9fd52aedf6484b345f30857d7f9d72bf` (Draft PR #1158), strict
projection/HTTP/API contracts passed 69 tests in 3.41s. The default full suite
passed 3,764 tests with 2 skipped in 178.26s, exit 0. The log also contains one
unclassified `Message`/`Arguments` request-log fragment; its origin remains
unresolved, so this is not a claim of completely clean diagnostics or a strict
full-suite run.

Separately built core/native wheels passed the manifest separation check.
SHA-256: core `f6043b274809ee67019375f5f3dd8ca8aef0e456f7ae8be1dffd801fdb75b957`;
native `b21cf8d0ce7601b3e7b788eba2bfd5f2a3a0cd74f723d151770b5f96953f625c`.
In `/tmp/co-latency-wheel-proof.OFezGW/isolated_env`, both noneditable import
origins were asserted under site-packages. Unmodified copies of the three
contract modules and two helpers ran outside the checkout with `python -I -m
pytest --noconftest ... -q -W error`: 69 passed in 24.71s, exit 0. This proves
the local macOS ARM64/Python 3.12 artifact slice, not hosted Linux or release.

The original added section at exact source `45cc666f` was directly inspected in
the actual GitHub browser, English, 1265 x 712, with readable wrapped commands,
hashes and headings and no observed overlap. These follow-up receipt paragraphs
and the complete code diff still need final visual inspection. No full product
UI, public release, protected approval, or customer KPI gain is established.

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
