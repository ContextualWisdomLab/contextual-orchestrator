# Provider request correlation

Status: proposed in PR #1105; not deployed. Runtime owner: CO. Log collector
owner: ContextualWisdomLab/.github.

Central run 34299034731/job 102308769876 used trusted workflow revision
`7fd571dbcdbae6acf29d8f4ee704d7ba6297e4db` and logged installation of CO
`414f22973658c4ddc3d4320fcf7acd9b4e8ba991`. Artifact 10085227363 contains
provider attempts without request identities. Timestamps and a final served
model cannot establish which earlier calls belong to the failed request.

At local regression commit `f7f05569a54a51c4cd6e42418a0c079b032d45f6`, a real
HTTP request reached the real client retry wrapper with a controlled failing
transport. Its two provider diagnostic lines lacked the error response ID:
1 failed, 46 deselected (5.34s). No external provider was called.

`c7468ecea009bae3a62413b4c54ab5a9b242bdff` binds a fresh server-generated UUID
to each HTTP handling scope using ContextVar and resets it in finally. The
error response reuses that identity; caller headers and error details cannot
replace it. A session hash is insufficient because several requests can share
a session. Copied contexts inherit identity, while reused workers without a
copied context do not. `8b82235e2b6db19682b0a255758c6796c41b3f55` extends the
identity to all seven provider attempt/retry/terminal diagnostic helpers.

Reproduce from this checkout with its project environment:

```sh
python -m pytest tests/test_telemetry.py tests/test_orchestrator_debug_logging.py -q
```

Result at the latter code revision: 68 passed in 25.60s. This covers controlled
HTTP failures, sequential same-session requests, copied worker contexts, nested
exception cleanup, and all seven diagnostic helpers. It does not prove
simultaneous HTTP isolation, every orchestration thread path, success-response
correlation, full-suite success, or customer latency improvement.

Collector compatibility remains a release prerequisite. The trusted central
collector uses end-anchored patterns for several events and truncates failure
messages before error text. It rejects new fields until repaired. The new ID is
32 lowercase hexadecimal characters, or `-` outside an HTTP request; for failed
attempts it precedes `error_message`, for other events it is the final field.
Never recover an ID from untrusted error text. Preserve old-format inputs and
verify exact-SHA producer/collector integration before adoption. Do not copy
collector code into CO or enable unfiltered logs. Timeouts and replay policy
are unchanged by this patch. Browser rendering remains unverified.

## Independent second incident

Follow-up at `6b24fe96` (local candidate, not the full-suite head): the success
summary also carries the request ID. A socket-identity assertion proves actual
keep-alive reuse; a two-party barrier followed by two distinct server-thread IDs
proves overlapping same-session HTTP handling rather than merely submitting
two tasks. Both requests retain distinct IDs and matching attempt/failure logs.
`python -m pytest tests/test_telemetry.py tests/test_orchestrator_debug_logging.py
tests/test_request_framing.py -q` passed 81 tests in 20.76s. This supersedes the
earlier simultaneous-HTTP limitation for these controlled failure cases only;
real provider integration and every orchestration worker path remain unverified.

Run 34306399309/job 102324739644 used the same trusted workflow and CO pins.
Artifact 10087151196 again records candidate_count=24, ready_count=1,
deferred_count=8, rejected_count=7, and account diversity=3. The caller reported
429 after 125.2s at 2026-09-09 03:31:41 UTC. Unlike the earlier incident,
the review interval beginning 03:29:35 contains no logged TimeoutError:
several Llama attempts precede DeepSeek at 03:31:40.995, which fails at
03:31:41.035 (about 40ms). TimeoutErrors at 03:27:17 and 03:28:47 belong to
the earlier preflight interval, not this review interval. These logs therefore
do not support attributing the final 429 to the default 90-second timeout.
Role/request attribution remains incomplete without correlation; keep the
timeout repair and this diagnostic repair as separate claims. No rerun or
provider call was issued during this read-only investigation.
