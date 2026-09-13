---
id: "0130"
title: "Surface the output-budget clamp in-band instead of silently or via headers"
status: proposed
proposed_date: "2026-09-13"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
related:
  - path: "docs/planning/adrs/0034-anti-heuristic-routing-evidence.md"
    relation: "extends-honest-evidence-pattern"
success_criteria:
  - metric: "clamp visibility"
    target: "a request whose explicit max_tokens/max_completion_tokens/max_output_tokens exceeds the served agent's max_output_tokens carries requested_output_tokens, effective_output_tokens, and output_budget_clamped on both the orchestration trace step and the OpenAI-shaped response"
    source: "tests/test_output_budget_model_max.py"
  - metric: "no new numeric ceiling"
    target: "no fixed cap is introduced; the agent's own catalog max_output_tokens remains the only ceiling enforced"
    source: "contextual_orchestrator/orchestrator.py::ModelClient._clamp_agent_token_budget"
---

# Surface the output-budget clamp in-band instead of silently or via headers

## Context

`ModelClient._clamp_agent_token_budget` rewrites any explicit caller budget
(`max_tokens`, `max_completion_tokens`, `max_output_tokens`) that exceeds the
served agent's published `max_output_tokens` down to that ceiling. The rewrite
is silent: no error, no adjustment field, no header, no trace step, and no
usage marker tells the caller that the budget it asked for was not the budget
applied. A response that later ends with `finish_reason=length` therefore
looks like an ordinary completion that ran out of the *caller's* own budget,
not the gateway's.

This was found during the local reproduction review of #1154 (removal of the
global generation-token ceiling per #1151). After #1154, a caller may
legitimately send a cap above one specific model's catalog maximum, so this
silent path becomes reachable by ordinary requests rather than only by
mis-sized ones. Filed as issue #1169.

Repository policy for generation limits: an explicit caller cap is
authoritative within the physical model limit; when it conflicts with the
physical limit the gateway must return either an explicit error or an
explicit adjustment result, never a silent truncation.

A response header cannot satisfy this. Streaming calls `_begin_sse()` in
`server.py` before the provider call runs, so response headers are already
flushed by the time the clamp is known; a header-based signal would therefore
be unavailable on the exact path (`finish_reason=length` after truncation)
that most needs it, and would still leave the non-streaming JSON body with no
way to carry the same fact for a client that only inspects the body.

## Decision

Expose the clamp in-band, in the same two places the gateway already reports
other honest-measurement caveats:

- **`usage_measurement_status`** on the top-level chat/text completion
  response already tells a caller when `usage` is `"measured"` versus
  `"unavailable"`.
- **`orchestration`** is the existing extension object carried on both the
  non-streaming chat completion response (`chat_completion_response`) and the
  final SSE chunk (`chat_completion_chunks`), already used for
  `workflow_run_id`, `mode`, `verification`, `cost`, and similar gateway
  annotations that are not part of the OpenAI wire contract.

This ADR reuses `orchestration` rather than inventing a new top-level key:

1. **Trace.** The orchestration trace row for the provider call that was
   clamped carries `requested_output_tokens`, `effective_output_tokens`, and
   `output_budget_clamped: true`. `ModelClient` records this on the same
   per-thread mechanism it already uses for `take_usage()` /
   `take_assistant_message()`
   (`_clamp_agent_token_budget_with_evidence` / `take_output_budget()`), and
   `TaskOrchestrator._invoke` exposes it the same way it exposes assistant
   extras (`_last_output_budget`, mirroring `_last_assistant_message`) so the
   `route`/`conduct` trace-row builders can attach it without changing
   `_invoke`'s return shape.
2. **Response.** The same three fields are copied onto the top-level
   `result` dict from the trace row associated with the answer actually
   returned (the single row for `route`; the last executed step for
   `conduct`), and from there into `orchestration` on both
   `chat_completion_response` and the final `chat_completion_chunks` frame,
   exactly like `cost` and `verification` already are.
3. **Unclamped requests.** When an explicit budget field was present but did
   not exceed the ceiling, the three fields are still emitted with
   `output_budget_clamped: false` -- the same explicit-absence-is-explicit
   convention `usage_measurement_status` already uses (`"unavailable"` rather
   than omitting the key). When no explicit budget field was present at all,
   nothing is added; there is no clamp decision to report, matching how
   `usage` itself stays `null` rather than acquiring a synthetic status.

No numeric cap is introduced anywhere by this decision. The only ceiling
enforced remains the served agent's own catalog `max_output_tokens`; this ADR
only makes an existing enforcement action observable.

### Rejected alternatives

- **Silent clamp (status quo).** Fails the "explicit adjustment or explicit
  error" policy outright; a truncated response is indistinguishable from an
  ordinary one.
- **Header-only signal.** Unavailable on the streaming path, where headers
  are flushed by `_begin_sse()` before the provider call and its clamp
  decision exist; would also require callers to inspect two different
  surfaces (headers for streaming semantics, body for everything else) for
  the same fact.
- **Hard-reject with HTTP 400.** Would break consumers (`noema`,
  `opencode`) that send a large `max_tokens` as a ceiling rather than a
  demand, turning a routine cross-model request into a hard failure instead
  of the best-effort completion those callers actually want.

## Consequences

- `finish_reason=length` next to `output_budget_clamped: true` now
  distinguishes "the gateway's catalog ceiling truncated this" from "the
  caller's own budget truncated this," closing the honesty gap the routing
  evidence work (ADR 0034) already established for usage and cost.
- `ModelClient` gains one more per-thread take-once accessor
  (`take_output_budget`), following the existing `take_usage` /
  `take_assistant_message` pattern instead of changing any public method
  signature; the direct unit test of `_clamp_agent_token_budget` itself is
  unaffected.
- Only the `route`/`conduct` single-call and per-step invocation path
  (`TaskOrchestrator._invoke`'s non-race branch) is wired for evidence in
  this change. The multi-endpoint `immediate_race` branch and the
  structured/`free_only` synthesis payload-builder call sites
  (`ModelClient._clamp_agent_token_budget` at the `_stream_send` and
  `proxy_send`/batch-request-body call sites) still clamp silently; carrying
  the same evidence through those paths is tracked as follow-up work, not
  claimed as complete by this ADR.

## Verification

- `tests/test_output_budget_model_max.py` asserts: a request whose explicit
  budget exceeds the agent's ceiling records
  `requested_output_tokens`/`effective_output_tokens`/`output_budget_clamped: true`
  via `ModelClient.take_output_budget()`, on the `route` trace row, and on
  `chat_completion_response`'s `orchestration` object; a request within the
  ceiling records `output_budget_clamped: false` in the same three places; a
  request with no explicit budget field records no clamp evidence at all.
- `tests/test_orchestrator_client_boundaries.py::test_client_clamps_known_provider_output_ceiling`
  (the existing direct test of `_clamp_agent_token_budget`) is unchanged and
  still passes, confirming the clamp's own enforcement behavior was not
  altered.
