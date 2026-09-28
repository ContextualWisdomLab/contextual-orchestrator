# Provider route outcome, API contract 0.3.3

Status: proposed. This contract requires a reviewed immutable gateway release
before a consumer pins it. `/v1/provider_readiness` reports preflight state; it
does not describe what happened to a particular request.

An inference-authorized caller sends a Chat Completions request with
`model: "orchestrator/free"` and retains the server-generated `x-request-id`
response header. The gateway owns candidate selection and fallback. A successful
streaming response places `orchestration.route` in its final completion chunk;
the route uses the same `OrchestrationRoute` and `OrchestrationRouteAttempt`
schemas published by the OpenAPI 0.3.3 contract. The `attempted` entries are in
execution order. `terminal_reason` is mandatory. Its values are `served`,
`eligible_set_exhausted`, `fail_closed`, `request_too_large_exhausted`,
`rate_limit_wait_budget_exhausted`, `rate_limited_storm`,
`pinned_candidate_failed`, and `stream_interrupted`; a missing or unknown value
is invalid. A `served` reason requires exactly one `served` attempt, while every
other reason forbids one. The final `served` entry identifies the candidate that
returned the completion; earlier entries distinguish failed candidates from `completed` answers that
were returned but not selected. `completed` does not establish answer quality
or provider health, and does not claim that the caller received that answer.
If a later round fails, the failure receipt retains those completed attempts
alongside the later failures and makes no final served claim. The final frame is
the success receipt. If the connection ends before it, the caller has no
authoritative served-candidate receipt and must treat the outcome as unknown.
If eligible candidates fail before sending content, the terminal SSE error detail
contains the same typed route with `terminal_reason: "eligible_set_exhausted"` or
`"fail_closed"`. A caller-pinned candidate failure has
`"pinned_candidate_failed"`; a failure after the provider emitted content has
`"stream_interrupted"`. Either may leave an incomplete stream. The caller must
not infer a served completion from partial bytes.
Quota exhaustion can return `rate_limit_wait_budget_exhausted` or
`rate_limited_storm`. These reasons do not establish when a provider recovers:
the gateway waits on provider timing when supplied, or on its configured
finite cooldown when the provider supplies none. In the latter case the
failure detail labels `cooldown_source` as `assumed`; any returned retry
interval is a gateway estimate, not a provider promise. Size exhaustion uses
`request_too_large_exhausted`. All preserve ordered failed attempts and forbid
a final served claim.

A provider `[DONE]` marker or non-empty `finish_reason` is an explicit
completion signal. If the provider connection closes with neither, the caller
receives a non-retryable `provider_outcome_unknown` 502 with a `fail_closed` or
`stream_interrupted` route, never a served receipt. Partial output does not
authorize replay.
The gateway does not retry that request on another provider because the
upstream outcome is unknown.

The route contains only configured candidate IDs, model names, typed outcomes,
upstream status when available, retryability, and a transport tag. It omits
provider response bodies, prompts, credentials, and error prose. A
`deadline_exceeded` attempt with `model_timeout` means the gateway's configured
model timeout elapsed. It does not mean the caller cancelled. A detected client
disconnect ends the stream and produces no deliverable final frame; a caller
must record its own cancellation or deadline locally. The gateway cannot infer
those causes from a broken connection or a provider timeout.

Tool-bearing chat requests use the synchronous completion path. Its route
evidence remains under the separate route-once change; this streaming addition
does not turn tool requests into SSE requests. An HTTP failure's typed error
detail remains the failure receipt. Neither a failed request nor a missing
terminal frame authorizes the caller to replay a tool session with unknown
side effects.
