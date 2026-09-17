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

## Concurrent HTTP follow-up

Follow-up at `6b24fe96` (local candidate, not the full-suite head): the success
summary also carries the request ID. A socket-identity assertion proves actual
keep-alive reuse; a two-party barrier followed by two distinct server-thread IDs
proves overlapping same-session HTTP handling rather than merely submitting
two tasks. Both requests retain distinct IDs and matching attempt/failure logs.
`python -m pytest tests/test_telemetry.py tests/test_orchestrator_debug_logging.py
tests/test_request_framing.py -q` passed 81 tests in 20.76s. This supersedes the
earlier simultaneous-HTTP limitation for these controlled failure cases only;
real provider integration and every orchestration worker path remain unverified.

## Independent second incident

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

## Exact-revision collector contract

The full suite at `7b7b32006e7ae498db2ee781bd423d9c7b6774fc` terminated
with exit status 0: **3399 passed, 2 skipped in 1594.26s**. This result predates
the success-summary and concurrent-HTTP follow-up; it must not be attributed
to their later revision. Those changes have the focused 81-test evidence above.

The published Markdown at that same revision was opened in Edge and its
1897 × 949 screenshot directly inspected. The visible upper document had readable
heading/body contrast, wrapped paragraphs and commit identifiers, and an unclipped
test command. This is an English desktop upper-viewport inspection only, not a
full-document, responsive, interaction, or product-UI visual acceptance result.

The producer candidate `7cb97ec8e2979d35b72c86a801ab18f0fd9c213d`
was cross-executed with the sanitizer from central PR #2053,
`fc0ab87bfde0900461034be815046914f9019bfc`. All seven actual provider
logging functions produced records whose trusted request ID survived sanitization.
A controlled error body containing a second, forged ID was omitted, as was its
controlled sensitive-text sentinel. Replacing the trusted ID with `INVALID`
or appending an embedded newline caused rejection for all seven records.
The final `request_failed` summary retained its ID and omitted trailing detail.
These are isolated, exact-revision contract checks, not live provider or release
evidence. The consumer deliberately leaves successful HTTP summaries outside
this PR's allowlist; that follow-up contract remains unverified.

Follow-up consumer `4a0125bf9f50d4d26355249011df03c3735b3abc` adds a strict
HTTP-summary allowlist. Against producer
`f588ca8c093ea7c9a86b857685bfbb1ce3c05fe2`, an actual local HTTP GET to
`/healthz` returned 200 and emitted one request summary. The new sanitizer
retained it verbatim, including the generated request ID. Appending a controlled
extra detail field or substituting a non-allowlisted path caused rejection.
This supersedes the missing-success-summary contract limitation for that one
route/state; it does not verify all routes, current production adoption, or
latency improvement. No external provider was called.

## Integrated full-suite failure

At `f588ca8c093ea7c9a86b857685bfbb1ce3c05fe2`, the integrated full suite
terminated with exit 1: **3399 passed, 2 skipped, 1 failed in 1767.82s**.
`test_http_responses_rejects_store_true` failed while constructing the server's
ModelClient, before HTTP assertions: `context.load_verify_locations` raised
`InterruptedError` (errno 4) while loading the certifi CA bundle. This does not
prove a response-correlation regression, but it also does not establish a green
suite or justify classifying the failure as a flake. Same-head isolated
reproduction is the next diagnostic step. Preserve this failure receipt even
if a subsequent isolated test passes.

The same-head isolated command `python -m pytest
tests/test_responses_store_http_honesty.py -q` then completed with exit 0:
4 passed in 20.05s. The interruption did not recur in this run; its signal or
operating-system trigger remains unproven. No TLS checks were bypassed and no
retry was added. A clean isolated run does not replace full-suite verification.
# Typed streaming error correlation

The chat and Responses SSE error adapters must retain the request identity
observed inside the provider invocation. They previously generated another UUID
when framing typed failures, breaking correlation despite correct provider logs.
The repair uses the ordinary HTTP error adapter's trusted identity convention.
This is an identity mismatch fix, not evidence of upstream detail injection.

Reproduce with `python -m pytest tests/test_stream_error_identity.py -q`.
Three real HTTP cases cover chat provider errors, Responses provider errors, and
chat stopped-tool errors. The Responses fixture fixes the routing choice to
isolate SSE framing; it does not test routing policy. The original cases failed
identity equality; after repair, these and both debug logging suites passed
(40 tests, 2.75 seconds). No hosted check or deployment is implied.

## Rate-limit storm (2026-09-14)

Distinct from the request-identity correlation issues above, but the same
provider-request-boundary area: org CI review lanes calling this gateway with
`orchestrator/free` saw every candidate return HTTP 429 within ~50ms during a
free-pool rate-limit storm (noema run 34758641142, strix run 34758679736:
preflight `ready_count: 0`, 7x 429 across OpenRouter and NIM accounts), and the
gateway failed the request instead of honoring the provider's declared
cooldown. `ContextualWisdomLab/.github#2148` root-caused the same failure mode
against a three-route OpenRouter `:free` ZDR pool wiped by a single 429 burst
(its item 1: "honor provider-stated Retry-After, no arbitrary retry budget");
`#2165` shows the resulting `noema-review`/`strix` failing closed on
gateway-side 429/502 after failover, with caller `attempts=1`.

Fixed: `Retry-After`/`x-ratelimit-reset*` parsing, a per-agent cooldown kept
separate from the health circuit breaker, a shared skip in
`_failover_candidates` for every caller, and one shared bounded
wait-then-retry (or honest `429 provider_rate_limited` with a `Retry-After`
header) implementation, `_await_rate_limit_recovery`, reached from both
`proxy_completion`'s passthrough failover loop and
`_invoke_with_rate_limit_recovery` -- the wrapper around `_invoke`, the shared
engine `route_once` and every `conduct` step use, so the real
`orchestrator/free` HTTP path this incident describes is covered, not just
direct-API passthrough use. Full detail and test evidence: the 2026-09-14
entry in [the gap baseline](../product-technical-gap-baseline.md).

The org sidecar's own preflight artifact (`contextual-orchestrator-preflight.json`)
already reports `candidate`/`probed`/`rejected_count` and
`account_skip_after_429` fields; those are the RED/GREEN evidence an external
CI run can use to confirm this class of fix without needing gateway-internal
access. This repo does not modify that org-owned sidecar script.

### Follow-up: a 429/503 with no cooldown header at all (2026-09-14)

The fix above still had a gap: `_record_rate_limit(agent_id, None)` returned
without recording anything, so a 429/503 whose provider omitted both
`Retry-After` and `x-ratelimit-reset*` (RFC 9110 10.2.3 permits omitting it
entirely, and NIM/OpenRouter routinely do) was never marked cooling --
`_await_rate_limit_recovery` saw no candidate to wait for, and the request
failed exactly as if this whole feature did not exist. The 2026-09-13
production storm may well have been exactly this shape.

Fixed: an unknown-duration 429 now records the administrator-owned
`rate_limit_unknown_cooldown_seconds` (constructor/CLI default 5s) as an
*assumed* cooldown instead of nothing, tagged `cooldown_source: "assumed"` in
`provider_readiness_report` and in the honest-429 error detail (vs
`"provider"` for a real `Retry-After`/`x-ratelimit-reset*` value); the
existing "cooldowns only extend forward" rule also protects the source label,
so a later assumed cooldown can never shorten or relabel an active
provider-stated one. Scoped to 429 specifically, not 503: a 503 ("service
unavailable") is a genuine, possibly permanent availability signal with no
inherent quota-recovery semantics, and extending the assumption to it made
several pre-existing exhaustion tests loop through repeated assumed waits
before finally raising the wrong (storm) error identity for what was actually
a permanent, unrelated failure -- concrete regression evidence, not a
guess. Also added: `_await_rate_limit_recovery` waits only for a virtual/
gateway-selected model (`GATEWAY_DEFAULT_MODEL`/`AUTO_MODEL`/`FREE_MODEL`, or
none) -- confirmed against `tests/test_provider_error_taxonomy.py`'s
single-candidate, explicit-concrete-model `rate_limit_exceeded` contract,
which this same-shaped defect (before this guard existed) made hang past its
5s client timeout. An earlier version of this guard keyed off candidate
count instead (fewer than two candidates meant "nothing to wait for"), but
that misclassified a virtual selector's pool wiped down to exactly one
eligible candidate by a 429 -- a real, common production shape, corrected in
the "explicit-vs-virtual selector" follow-up below -- identically to a
genuinely pinned concrete model, and failed the request immediately instead
of waiting. The discriminator is now whether the caller delegated selection
at all, not how many candidates happen to remain.

Tests added to `tests/test_rate_limit_aware_admission.py`: a
no-Retry-After/no-header 429 storm across two candidates still waits the
assumed cooldown and is served; the same with zero budget returns
429/`provider_rate_limited` with `Retry-After` equal to the ceiled assumed
value and `cooldown_source: "assumed"` in the error detail; a provider-stated
cooldown is never shortened or relabeled by a later assumed one. Two
pre-existing tests in `tests/test_passthrough_provider_failover.py`
(`test_all_candidates_chain_the_last_failure`,
`test_free_virtual_model_never_fails_over_to_a_paid_agent`) used a bare 429
purely incidentally (to represent "some transient failover-eligible
failure", not to test rate-limiting itself) and were switched to 500 to keep
that intent isolated from this feature.

### Follow-up: explicit-vs-virtual selector, not candidate count (2026-09-14)

The "two or more candidates" guard above was itself a defect, not just a
narrow scope choice: `_await_rate_limit_recovery` opened with
`if len(candidates) < 2: return False`, so a pool with exactly one eligible
candidate never waited out a storm -- it failed immediately, which is the
behavior this whole feature exists to remove. Production evidence this case
is real and common: noema-review run 34772771262 (sidecar pin `767e67fb`) on
contextual-orchestrator#1177 reported preflight `ready_count: 1`, and the
review call then failed after 562s with `HTTP Error 429` served by
`google/gemma-4-31b-it:free`; `ContextualWisdomLab/.github#2148` records that
the private-target ZDR pool is three OpenRouter `:free` routes on a single
account, so one 429 wipes the whole pool down to at most one eligible route.

The guard existed for a good reason that had to be preserved:
`tests/test_provider_error_taxonomy.py::test_chat_completions_returns_openai_compatible_rate_limit_error`
pins one named concrete model that always answers 429 with no headers; under
an assumed-cooldown-always-waits path that request hangs past its
client-side read timeout. The correct discriminator was never the candidate
count -- it is whether the caller delegated selection at all: an explicit
concrete model must fail fast with the honest 429 (unchanged), while a
virtual selector (`GATEWAY_DEFAULT_MODEL`/`AUTO_MODEL`/`FREE_MODEL`, or no
model) must wait even when only one candidate remains.

Fixed: `_await_rate_limit_recovery` gained a keyword-only `virtual_selector`
parameter that both `proxy_completion`'s passthrough loop and
`_invoke_with_rate_limit_recovery` (in turn threaded from `route_once`'s and
`conduct`'s own `model_name in {GATEWAY_DEFAULT_MODEL, AUTO_MODEL,
FREE_MODEL}` check) compute once and pass through, replacing the
`len(candidates) < 2` guard. Tests added to
`tests/test_rate_limit_aware_admission.py` cover a virtual selector with
exactly one eligible candidate that 429s with `Retry-After: 1` then succeeds
on retry (waits once, served), the same shape with no budget (honest 429),
and an explicit concrete model with a single always-429 candidate (fails
fast, no wait).
