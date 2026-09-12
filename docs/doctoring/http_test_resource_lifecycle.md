# HTTP test resource lifecycle

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
