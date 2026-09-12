# HTTP test resource lifecycle

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
