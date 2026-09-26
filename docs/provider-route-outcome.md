# Provider route outcome, API contract 0.3.1

Status: proposed. This contract requires a reviewed immutable gateway release
before a consumer pins it. `/v1/provider_readiness` reports preflight state; it
does not describe what happened to a particular request.

An inference-authorized caller sends a Chat Completions request with
`model: "orchestrator/free"` and retains the server-generated `x-request-id`
response header. The gateway owns candidate selection and fallback. A successful
streaming response places `orchestration.route` in its final completion chunk;
the route uses the same `OrchestrationRoute` and `OrchestrationRouteAttempt`
schemas published by the OpenAPI 0.3.1 contract. The `attempted` entries are in
execution order. `terminal_reason` is mandatory and has exactly three values:
`served`, `eligible_set_exhausted`, or `fail_closed`; a missing or unknown value
is not a valid receipt. The final `served` entry identifies the candidate that returned
the completion; earlier entries describe failed candidates. The final frame is
the success receipt. If the connection ends before it, the caller has no
authoritative served-candidate receipt and must treat the outcome as unknown.
If eligible candidates fail before sending content, the terminal SSE error detail
contains the same typed route with `terminal_reason: "eligible_set_exhausted"` or
`"fail_closed"`. A failure after content has begun may leave a partial stream;
the caller must not infer a served completion from those bytes.

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
