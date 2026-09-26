# HTTP test resource lifecycle

## Review follow-up, 2026-09-20

Base `26b71dbbef11f1779a83495b0b2096a6bd7e2c3d` (#1210): seven
previously identified strict failures reproduced, exit 1 (6.25s). All seven
are test-owned HTTPError objects: three header inspections, the stopped/generic
409 classifier, and three fake chat implementations that convert responses
into typed failures without handing the raw response to ModelClient.
The classifiers borrow responses; they must not close their callers' handles.

Explicit response scopes now close these objects, including sibling logging,
status-classification, exhausted-pool and tool-shaped-message tests. Closing
assertions run after each scope; reused responses remain open across retries.
No production cleanup, endpoint, retry or security policy changes in this slice.

Isolated Python 3.14 source command (no cargo/maturin build):
`python -m pytest -q -W error --tb=short tests/test_rate_limit_aware_admission.py tests/test_provider_reliability.py tests/test_http_resource_lifecycle.py`.
The two original modules alone were 21 failed/63 passed (25.66s, exit 1).
After repair, the three-module command is 117 passed/4 failed (25.67s, exit 1).
The seven named failures and sibling resource failures are absent. All 37
HTTP lifecycle tests passed, including final cleanup, close-before-backoff,
cleanup-error preservation, and raw caller-owned response handoff. These use
transport doubles; they are not deployed endpoint or wire-delivery evidence.
The four remaining failures are three allowlist error-taxonomy assertions and
one missing selection_design field, not ResourceWarnings. Full-suite and
protected-delivery acceptance remain unverified.

## Separate allowlist endpoint follow-up, 2026-09-20

The resource-cleanup slice above exposed three independent taxonomy failures:
`_validate_allowlisted_provider` replaced EgressWeave rejection with plain
RuntimeError, bypassing existing ProviderUpstreamError handling. The shared
validator now emits a bounded, non-retryable provider_connection_error with
client status 502 and unknown provider status. The deny decision, resolved
address reuse, and no-send boundary remain unchanged; passthrough keeps its
existing transport reclassification.

Two real loopback HTTP regressions call Chat Completions and Responses through
build_server and the real ModelClient admission path. With the unchanged
production source at `e77087a131f1347d943215c9b3a55645d0f407a1`, both return
500/internal_error (2 failed, exit 1). With the repair, both return JSON 502;
transport sentinels record zero upstream calls and all client/listener handles
close. Together with the four existing allowlist regressions: 6 passed, 46
deselected, exit 0. These are local non-streaming endpoint checks, not deployed
provider health or successful inference. An exploratory streaming assertion was
removed because concrete Responses streaming is rejected as invalid_stream and
Chat streaming uses SSE rather than the assumed non-streaming JSON contract;
no streaming fix or acceptance is claimed.

## Request receipt and virtual-response follow-up, 2026-09-20

At #1212 `898a7cb97fac7b10d35e7ca6e5e0d2484d3a29cf`, the remaining
selection_design KeyError comes from dropped implementation: the tests remain,
but request snapshot scoping, selection attempt collection, and receipt
construction are absent. Reuse the request/receipt hunks of existing #1088
commit `e569cefa70079a64734ac0f5e47965f9efec3f3d` and its deployment-hash
fixture update. Do not copy its dependency, ranking/prior, or persistence changes.
Worker receipts capture attempts before the nested judge and exclude earlier
worker rounds. A strengthened API regression checks that the judge is absent.

An expanded strict run passed 175 test bodies but exited 1 during final cleanup:
five raw 429 responses leaked from the virtual proxy caller of proxy_send_once.
This is production ownership, distinct from #1211's test-owned classifiers.
The virtual loop converts those raw responses to typed errors; it now closes
in finally after classification/cooldown diagnostics, before failover or return.
Cleanup Exception does not replace the original outcome; BaseException remains
unmasked. Two direct closure assertions fail on the unchanged #1212 source and
pass after repair, including an injected cleanup OSError. Together with the
original KeyError, this bounded RED is 3 failed, exit 1.

A wait-round test used a 10ms real cooldown with a fake sleep. Under host pressure
the cooldown expired during execution and the test missed its intended branch.
It now advances a controlled monotonic clock with its sleep hook; production
cooldown policy is unchanged.

Historical non-target source validation at commit
`fea207fc4dde4a0bd6bb45ad75baebc21b9cbd19`: 179 passed, 21.91s,
process exit 0, under -W error across
rate-limit admission, provider reliability, HTTP resource lifecycle, API contract,
request policy/effort snapshots, and the existing stream receipt and race-failover
receipt cases. Four selection-receipt identity tests separately pass, exit 0.
The isolated environment used binary-only numpy 2.5.3 and fast-mlsirm 0.11.3
wheels to collect the latter module; no native build or numerical experiment ran.
That differs from this head's locked fast-mlsirm 0.11.4 runtime. These
historical dependency versions do not establish locked-install, complete-suite,
hosted-gate, independent-review or protected-merge acceptance.

## Lint and hash-locked install follow-up, 2026-09-20

Independent source review runs on MacBookAir as Orca task task_2228be0c8458,
dispatch ctx_35aa434c1886, against unchanged PR1210-1213 heads. It is an
independent agent review, not a substitute for non-author GitHub approval.

At #1213 fea207fc, Ruff reports two F821 errors where a nested recovery helper
captures the exception-target name. Bind the original ProviderUpstreamError as
a default argument to preserve the exact exception without a free exception-cell
reference. The bounded changed-file Ruff check and security.yml actionlint pass.

The actual require-hashes installer rejects the VCS fast-mlsirm requirement
before installing. Reuse #1088's fast-mlsirm0.11.3 and anyio4.14.2 declarations
and runtime-contract fixture; regenerate requirements.lock with uv pip compile
and uv.lock with uv lock, never hand-edit hashes. A binary-only dry-run targeting
Python3.12/Linux x86_64 verifies the46-package installation plan, exit0. The
macOS3.14 attempt instead fails a NumPy2.5.2 artifact hash mismatch; refreshing
NumPy index metadata reproduces the same lock entries. No hash bypass or
macOS locked-install acceptance is claimed. Pinned-metadata pip-audit using
--no-deps --disable-pip reports46 dependencies and zero known vulnerabilities;
this does not validate downloaded artifacts or replace the hosted audit/SBOM gate.

Rate-limit admission, released-runtime contract and repository security metadata
regressions:49 passed in13.66s, strict warnings, exit0. No native build ran.

## Independent conduct-receipt correction

Review https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1213#pullrequestreview-5259873532
reproduced request-wide attempt accumulation across conduct roles and incorrect
selected deployment after failover. The same issue also appeared in the separate
exact-head acceptance comment. Capture the attempt offset at each step and resolve
the returned served_id through the configured agent lookup before constructing
the receipt. Unknown served identity raises instead of fabricating provenance.
Three regressions (ordinary conduct, fail-first worker, unknown identity) fail
on the original implementation. Existing candidate selection, denial and retry
policies are unchanged. Original PR heads remain immutable; this successor
requires its own exact-head review and hosted checks.

## Trace HTTP fixture successor, 2026-09-13

Base: #1140 at `38c0603af2fd8fcb204f65be47081ada9d6bd35c`.
Candidate: `e88562187b7ab3bf681b306ab98d2ca821ae82ed`.
An inventory of 96 open PRs found no target-file overlap before editing.
The original trace-purpose singleton failed with warnings-as-errors (1 failed,
1.03s, exit 1; `/tmp/co-trace-successor-red-38c0603a.log`).
Regression checkpoint `a9de9de5` retained HTTPError handles and failed all eight
GET/POST, valid/malformed JSON, cleanup-OSError cases (1.08s, exit 1;
`/tmp/co-trace-helper-explicit-red.log`).

Ownership path: test `_post`/`_get` invokes urllib against the local server;
trace authorization raises RequestError, which the server serializes as 401.
urllib creates the client-side HTTPError consumed by the test helper. Closing
production provider responses cannot close this separate client object.
The helpers now close after decoding in `finally`; cleanup OSError cannot
replace decoded diagnostics or the primary JSON decoding exception. All 23
test-owned listener teardowns now call `server_close()` after shutdown/join.
Production authentication, routing, retries and response bodies are unchanged.
No global cleanup, warning suppression or forced collection is used.

At the unchanged candidate above:

| Check | Result | Log |
| --- | --- | --- |
| Trace module, strict | 31 passed, 1.77s, exit 0 | `/tmp/co-trace-helper-green.log` |
| Trace + HTTP lifecycle + passthrough + provider taxonomy, strict | 126 passed, 6.17s, exit 0 | `/tmp/co-trace-related-e8856218.log` |
| Full default | 3670 passed, 2 skipped, 157.76s, exit 0 | `/tmp/co-trace-full-default-e8856218.log` |
| Full strict | 1173 failed, 2494 passed, 2 skipped, 13 errors, 304.38s, exit 1 | `/tmp/co-trace-full-strict-e8856218.log` |

Use the shared interpreter documented below with `-m pytest tests -q --tb=short`;
strict adds `-W error`. Worktree: `/tmp/co-trace-http-resource-successor-20260913`.
Independent read-only review found no actionable issue and reproduced 31 strict
passes in 2.28s, exit 0. Cleanup injection covers OSError after underlying close,
not arbitrary exception classes or an underlying close that cannot complete.
The full strict failure list contains no target-module failures; this does not
prove every remaining failure's cause. Aggregate counts are not a latency KPI
or a causal percentage improvement. Full strict acceptance, hosted review,
protected merge and deployment remain unproven. Later documentation commits
must not relabel these tests as executed at a different head.

## Expanded repair checkpoint (unpublished)

### Final frozen-candidate verification

Candidate `345ee6b2b2ba2cdf6d415c9af8e47e5b715600e8` remained unchanged during
all three runs. Focused strict: **275 passed in 5.64s**, session 53191, exit 0.
Full default: **3662 passed, 2 skipped in 136.95s**, session 9331, exit 0.
Full strict: **1188 failed, 2470 passed, 2 skipped, 13 errors in 313.62s**,
session 7712, exit 1. Logs are `/tmp/co-resource-final-focused.log`,
`/tmp/co-resource-final-default-345ee6b2.log` and
`/tmp/co-resource-final-strict-345ee6b2.log` respectively. This final receipt
is a documentation-only follow-up; it does not relabel prior tests as executed
at its own later commit. The strict result remains unresolved. Draft publication
must not imply full strict acceptance, protected merge or deployment.

### Current checkpoint: 2026-09-13

At `69a5c26b52601832b5faa6ee23a8f7251816038c`, the eight-module strict
union passes **274 tests in 6.58 seconds, process exit 0** (session 11593;
`/tmp/co-resource-expanded-69a5c26b.log`). This supersedes the earlier RED
eight-module observation below, not its historical record. The complete strict
suite ended with **1193 failed, 2467 passed, 2 skipped, 11 errors in 284.63s**,
session 24872, process exit 1. Log:
`/tmp/co-resource-full-strict-69a5c26b.log`. Remaining failures are not accepted
as baseline exceptions without independent root/overlap classification. The
default suite completed with **3661 passed, 2 skipped in 152.37s**, session
68953, process exit 0; log `/tmp/co-resource-full-default-69a5c26b.log`.
This demonstrates default-suite success for this exact worktree, not equivalence
to the export worktree's larger test population or strict-warning acceptance.

Full-file warning aggregation finds 738 HTTPError, 673 socket and 18 SQLite
ResourceWarning occurrences. These count printed warning occurrences, not unique
objects, causal defects or failed tests. The largest failed-node module counts
are trace HTTP honesty (23), response-format HTTP honesty (22), multimodal model
group HTTP (20) and cost-review server (18). Module attribution alone does not
prove ownership: delayed finalization can surface in a later unrelated test.
An initial tool-output aggregation was truncated and is not evidence; these
counts were recomputed directly against the complete log. The earlier export
worktree's 1287-failure/15-error baseline has a different collected population;
do not report an improvement percentage without an exact per-node comparison.

Residual singleton audit at `f598d982`: trace HTTP honesty's
`test_trace_requires_a_verified_trace_purpose` independently fails in 1.85s,
exit 1 (session 81224; `/tmp/co-trace-resource-singleton-f598d982.log`). It emits
an HTTPError 401 finalizer warning and an unclosed listener warning. Its helper
reads HTTP errors without closing; teardown stops and joins the server without
closing its socket. That file has no delta against #1140's remote `eeed2d98`.
This establishes a remaining test-owned boundary, not whole-baseline equivalence
or authorization to rewrite other open PRs. Hunk ownership coordination precedes
any repair in that module.

The union consists of SQLite fixture lifecycle, HTTP resource lifecycle, agent
pool DB, tool execution fallback, provider error taxonomy, OpenAI passthrough,
true streaming and Actions model fallback tests. It uses the shared project
interpreter at
`/Users/seonghobae/Documents/ChatGPT/contextual-orchestrator/.venv/bin/python`
from this worktree, with `-m pytest -q -W error --tb=short`. This is source-tree
test evidence, not an independently installed package or native release proof.

- `8182dd73`: retained-response assertions reproduce both raw 404 and binary
  503 ownership failures (2 failed, exit 1), without relying on GC timing.
- `c0a2170d`: consumed raw/binary responses close after classification; retry
  responses close before backoff. Original HTTPError handoff remains open when
  `allow_transient_retries=False`; its receiving caller owns consumption/close.
- `68a73663` and `88440c78`: cover raw final/intermediate cleanup failures,
  preserved primary classification, caller-owned handoff identity/lifetime and
  binary cleanup failure. Taxonomy plus lifecycle: 62 passed, exit 0.
- `82d478c7`: closes 11 test-owned listening sockets after shutdown. The
  passthrough module improved to 31 passed/1 failed; the remaining two 413
  responses were production-owned, not test-fixture cleanup obligations.
- A read-only threaded call profile of that failing test observed
  `proxy_completion`, `_orchestrated_provider_completion`, and `send_synthesis`
  once each, and no `proxy_capability` call. Evidence:
  `/tmp/co-413-owner-call-trace.log` (exit 1). Fixing a similarly named sibling
  would not have addressed this actual execution path.
- `69a5c26b`: closes each consumed synthesis HTTPError in `finally` after its
  diagnostics, candidate observation and classification. Cleanup exceptions
  cannot replace its primary outcome. Passthrough: 32 passed, exit 0.

Independent read-only review found no production semantic blocker in
`c0a2170d`/`69a5c26b`; the reviewer independently ran 37 lifecycle tests in
1.79 seconds with exit 0 (session 25520). It identified missing direct synthesis
cleanup-failure and close-before-next-candidate assertions. `dc88b2f3` adds both
to the existing two-candidate HTTP 413 scenario: the next send asserts earlier
responses are already closed; both retained responses must be closed before
test cleanup; a closer that raises after closure must preserve the final 413.
The test does not close errors in the fake sender. Its fallback cleanup runs
only after the assertions to avoid leaking resources on RED. The passthrough
module passes 33 tests in 2.69s, session 72459, exit 0. Full-suite results above
remain tied to `69a5c26b`, not this later test-only head. Changed-file
syntax parsing (7 Python files) and `git diff eeed2d98 HEAD --check` both pass
at `69a5c26b`. The checked-in local quality workflow and `pyproject.toml` do
not specify a Ruff/Black/Mypy gate; syntax/whitespace checks are not substitutes
for type checking or security analysis. No new lint policy was invented here.

The revised checkpoint's top and evidence/review sections were rendered with the
installed Marked renderer and directly inspected in the in-app browser at
`http://127.0.0.1:65278/` (English, 1265×712, tab 39). The screenshots showed
readable headings, wrapped hashes/paths, adequate spacing and contrast, and no
overlap or horizontal clipping in those viewports. Screenshots were viewed
directly in the tool output, not saved as durable image files. Remaining historic
sections, responsive widths and a final post-edit capture remain uninspected;
this is a partial document visual receipt, not full UI/locale acceptance. No claim of
full-suite acceptance, protected merge, release, deployment, actual routing
accuracy gain or customer decision-latency gain follows from these unit tests.

### Earlier checkpoint retained for provenance

At `5d498b5ed30b8ce46e2e2041533b6c5070904cac`, the four-module resource
union passes 150 tests with warnings as errors and process exit 0 (2.78 seconds,
session 7722). The eight-module expansion remains RED: 31 failed, 226 passed
in 10.94 seconds, session 23491, exit 1. Full log:
`/tmp/co-resource-expanded-5d498b5e.log`. This is not whole-suite acceptance
or a measured customer accuracy/decision-latency gain.

The SQLite fixture change (`d05a83d6`) preserves transaction exit before close;
explicit handle assertions changed from 9 failures/1 pass to 10 passes.
Test HTTP helper/listener cleanup (`00ffc012`, `94982670`, `febef47f`) remains
separate from production ownership. `3a014a40` accidentally wrapped a plain
TimeoutError in a response context; standalone execution exposed TypeError.
`3068a5cb` restores that test's semantics and scopes closure to its intended
HTTPError caller. Preserve this failed attempt as a mixed regression, not a
clean improvement in aggregate failure count.

The fake-client cleanup experiment `997113de` was explicitly discarded by
revert `fba09c8d`: its green result masked production retry-boundary ownership.
The actual owner fixes are `2b69dbc2` (final classification, four RED status
cases) and `5d498b5e` (close before retry backoff, success/final-failure RED
cases). Final classification reads diagnostics before closing; a close error
cannot replace the classified primary error. Generic classifiers are unchanged.
Tests preserve attempt counts, backoff delay and final provider status.
Independent review and expanded failure repairs remain pending. Nothing in
this checkpoint establishes protected merge, release or deployment.

## Stacked transport follow-up (not published)

The sections below retain the initial test-only checkpoint. The current local
successor instead starts at #1135 exact
`c7ed39397bd8771b44250a61ab0ee8818889152a` and cherry-picks that checkpoint as
`87dcc53fb868bfa615c27c42fdc73aa69c4f1875`. The complete `_stream_send` AST,
response-limit expression and streaming test delta preserve #1128's contribution;
this does not establish full succession of every other #1041 PR.

The HTTP 500 reproduction failed on this stack before the production change
(1.86s, `/tmp/co-stream-resource-successor-red.log`). `_stream_send` now closes
HTTP error responses in `finally`, after body classification and on terminal
tool-stop paths. Response-limit passthrough remains intact. A cleanup exception
must not replace the safe primary error or leak provider diagnostics.

Independent review found that a failing custom response closer could do exactly
that. The first regression attempt failed on an invalid mock URL, not this defect;
after fixing its HTTP URL, it failed with the raw cleanup diagnostic in 0.98s.
Best-effort closure fixed that failure. Tests cover both ordinary HTTP 500 and
terminal tool-stop errors. The latest three-file run passed **56 tests in 1.76s**
with warnings as errors (`/tmp/co-stream-resource-final-focused.log`).

The expanded five-file transport run is not clean: parent 21 failed/90 passed/
1 error, successor 22 failed/89 passed/1 error. Five telemetry node outcomes
differed. Running those five alone produced the same one resource-warning
failure and four passes in both trees. This suggests collection-order-dependent
warning attribution but does not prove equivalence. Every node in the observed
failure union was compared in independent processes (session 53963, exit 0).
All 25 nodes ran once on each tree: 50 processes, identical per-node exit codes,
22 nodes failing on both trees and three passing on both. Core warning/error
signatures matched after ignoring process-specific memory addresses and loopback
ephemeral ports; those two normalizations do not discard error types or status
codes. Raw results are in `/tmp/co-stream-resource-isolated-union.jsonl`.
This is a bounded, order-dependent baseline limitation, not a clean expanded
suite or proof of no regression outside the observed union. Subsequent focused
tests including the terminal tool-stop cleanup path passed **56 in 1.76s**.
Independent final review found no actionable defect in the revised cleanup.
Full-suite acceptance and rendered-document inspection remain pending. No push,
PR, merge, deployment or numerical KPI improvement is claimed.

## Scope and cause

This isolated repair starts at protected main
`012beaacd0631f8cd3391c77744eeb626269b5de`. It changes test-owned resources only.
Python 3.14.6 with pytest and `-W error` reported unclosed listening sockets and
implicitly finalized `HTTPError` bodies. `shutdown()` stops the serving loop;
it does not close its socket. The shared `_post` helper read an error body
without closing it, including when JSON decoding raised.

The two SSE context managers now close their servers and join their threads.
Existing direct teardowns in the two affected test modules close their servers.
The shared error handler uses the error response as a context manager, preserving
its status/body contract and closing it on malformed JSON too. No warning filter,
production transport, optimizer policy, dependency or model timeout changed.

## Reproduction and evidence

Use the existing project Python environment from the isolated checkout:

```sh
/Users/seonghobae/Documents/ChatGPT/contextual-orchestrator/.venv/bin/python -m pytest tests/test_http_resource_lifecycle.py tests/test_true_streaming.py tests/test_actions_model_fallback.py -q -W error --tb=short
```

Before repair, the original streaming and sticky-502 cases failed twice in
3.27s (`/tmp/co-http-resource-red-20260912.log`). Four explicit regression
cases then failed in 0.99s before implementation
(`/tmp/co-http-resource-contract-red-20260912.log`): both provider context
sockets stayed open, and both valid/invalid JSON error bodies stayed open.
The tests close resources in their own finalizers even on assertion failure.

The four explicit cases plus the original two reproductions passed together:
**6 passed in 1.10s**, session 64287, warnings as errors. This verifies the
test-owned cleanup boundaries, not all transport paths.

After repair, the related suite returned **52 passed, 1 failed in 2.80s**
(`/tmp/co-http-resource-related-20260912.log`, session 39289). The remaining
`test_stream_send_hides_raw_provider_error_text_and_cause` reports an implicitly
closed HTTP 500 response in the production streaming path. This is not GREEN
acceptance of the suite. Production edits are paused pending transport-owner
coordination; do not hide the warning or drop this test.

Exact cached diffs subsequently confirmed both #1128 (`d89921f6`) and #1135
(`c7ed3939`) modify the same `_stream_send` exception-handling block to preserve
`ProviderResponseError`. Closing HTTP errors must also preserve early tool-stop
raises and allow error-body classification before closure. Production edits
stopped at this overlap; the transport owner must integrate that lifecycle change.
Independent read-only review found no actionable defect in the test-only diff.

## Coordination and limits

An inventory of all 89 open PRs included complete file lists. Six PRs touch
`test_true_streaming.py`: #911 (`e8094918`), #1012 (`0a3f7dd2`), #1064
(`4c4e5f13`), #1067 (`a553b965`), #1128 (`d89921f6`), #1135 (`c7ed3939`).
Their exact cached Git deltas did not modify the repaired teardown hunks.
No open PR touched `test_actions_model_fallback.py`. REST subsequently hit its
rate limit; cached exact objects supplied the hunk comparison, not guessed titles.
Preserve every existing PR delta and revalidate ownership before publication.

The prior optimizer full-suite result (1306 failures, 15 errors) is not wholly
explained by these examples. No full rerun, hosted acceptance, release or real
accuracy/latency gain is claimed. PR #1137 remains unchanged. Rendered-document
visual inspection is pending; this runbook is not a completed visual receipt.
