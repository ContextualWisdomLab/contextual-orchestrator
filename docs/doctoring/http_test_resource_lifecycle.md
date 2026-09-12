# HTTP test resource lifecycle

## Expanded repair checkpoint (unpublished)

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
