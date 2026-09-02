---
id: "0126"
title: "Bidirectional Chat Completions <-> Responses shape translation"
status: accepted
proposed_date: "2026-09-02"
accepted_date: "2026-09-02"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/chat_responses_shape.py"
  - "contextual_orchestrator/provider_api_version.py"
  - "contextual_orchestrator/orchestrator.py"
related:
  - path: "docs/planning/adrs/0002-explicit-local-mlx-evaluation.md"
    relation: extends
  - path: "docs/planning/adrs/0035-structured-provider-orchestration.md"
    relation: constrained-by
success_criteria:
  - metric: "dual endpoints, either caller shape"
    target: "/v1/chat/completions and /v1/responses both already exist as public routes (server.py) and both serve a correct same-shape response regardless of which shape the selected agent natively speaks"
    source: "tests/test_chat_responses_shape.py::test_chat_shaped_request_routed_to_responses_only_agent_translates_both_ways and test_responses_shaped_request_routed_to_chat_completions_only_agent_translates_both_ways"
  - metric: "unknown capability never regresses working passthrough"
    target: "an agent with no api: tags gets identical behavior to before this ADR -- plain passthrough in whichever shape the caller sent -- for both endpoints"
    source: "tests/test_chat_responses_shape.py::test_untagged_remote_agent_gets_plain_passthrough_for_responses and tests/test_telemetry.py::test_stream_and_passthrough_provider_calls_create_client_spans"
  - metric: "round-trip fidelity on realistic payloads"
    target: "multi-turn messages, tool calls, and tool results survive translation in both directions with byte-identical text content"
    source: "tests/test_chat_responses_shape.py (fixture-based round-trip tests)"
  - metric: "per-provider API version isolation"
    target: "a provider with a declared header or query-param version sends it on every request; an undeclared provider sends none; one provider's version never appears on another's request"
    source: "tests/test_chat_responses_shape.py (API-version mechanism tests)"
---

# Bidirectional Chat Completions <-> Responses shape translation

## Context

`/v1/chat/completions` and `/v1/responses` already exist as public endpoints
(`server.py`), and a request-shape translation already existed --
`_responses_to_chat_payload`/`_chat_to_responses_payload` in
`orchestrator.py` -- but scoped to exactly one case: ADR 0002's local mlx-lm
workers, which speak only Chat Completions while Codex-style callers send
Responses shape. `ModelClient._proxy_send` gated that translation on
`_is_local_provider_url(agent.base_url)`. Every other provider/endpoint
combination fell through to verbatim passthrough: the payload the caller
sent was forwarded unchanged to `POST {base_url}/{endpoint}`, on the
assumption that whichever endpoint the caller named, the selected provider
speaks that shape natively. There was no signal recording which shape(s) a
given agent actually supports, and no mechanism for a provider that requires
a versioned API (a header like Anthropic's `anthropic-version`, or a query
parameter like Azure OpenAI's `api-version`) to get that version applied
automatically -- `grep`ing the whole tree for version-header handling found
nothing.

This gap is real: a caller can select a *specific* configured model on
either endpoint (only *streamed* Responses passthrough is restricted to the
virtual `orchestrator/auto`/`orchestrator/free` routing models --
non-streaming passthrough accepts a named model on both endpoints), and
nothing checked that the selected agent's provider actually implements that
shape before forwarding.

### The default direction matters more than it first appears

The first implementation of this ADR made every undeclared agent default to
"does not support Responses" for the purpose of routing a Responses request
-- i.e., translate to chat unless positively declared otherwise. That broke
`tests/test_telemetry.py::test_stream_and_passthrough_provider_calls_create_client_spans`,
which asserts that an ordinary `https://provider.example/v1` agent tagged
`provider_name="openai"`, carrying no tags at all, still gets a *verbatim*
`/v1/responses` passthrough call today -- because real OpenAI (and,
increasingly, other frontier providers) genuinely serves both shapes
natively, and every provider currently configured in
`model_discovery.PROVIDER_MODEL_SOURCES` is plain OpenAI-compatible chat.
Defaulting an *unlabeled* agent to "needs translation" would have silently
downgraded every currently-working Responses passthrough call to a lossy
round trip through Chat shape, for every provider that happens not to carry
a tag yet -- the opposite of ADR 0035's explicit "capability tags are
positive declarations, not proof of incompatibility."

## Decision

### Translation module boundary

`contextual_orchestrator/chat_responses_shape.py` is the one place shape
translation logic lives -- a dedicated, stateless, pure-function module
(mirroring `model_discovery.py`'s `style`-keyed catalog parsers), never
scattered inline in `server.py` route handlers. It exports four pure
functions, one per direction per body kind:

- `responses_request_to_chat_request` / `chat_response_to_responses_response`
  (the pre-existing pair, moved here unchanged and kept bound under their
  original private names in `orchestrator.py` for backward compatibility
  with existing tests that import them from there).
- `chat_request_to_responses_request` / `responses_response_to_chat_response`
  (new: the mirror direction, needed for a Responses-only-declared agent
  serving a Chat-Completions-shaped caller request).

`ModelClient._proxy_send` (`orchestrator.py`) is the single choke point
where a request actually leaves the gateway for a provider -- both
`TaskOrchestrator.proxy_completion` (direct single-agent passthrough) and
`TaskOrchestrator._orchestrated_provider_completion` (the conducted
evidence-workflow's final synthesis call) route every provider call through
it via `self.client.proxy_send`/`proxy_send_once`. It now carries two shape
branches instead of one:

1. `responses` endpoint + agent proven chat-only (local mlx-lm's proven
   `_is_local_provider_url` signal, unchanged, **or** the new
   `api:chat_completions_only` tag) -> translate down to chat, call, translate
   the reply back up.
2. `chat/completions` endpoint + agent proven Responses-only (the new
   `api:responses_only` tag) -> translate up to Responses, call, translate
   the reply back down.

Every other combination -- which is every agent configured today -- falls
through to the pre-existing verbatim-passthrough branch, unchanged.

### Capability signal: exclusivity tags, not additive ones

`agent_supports_responses(tags)` and `agent_supports_chat_completions(tags)`
read two new tag values on `ModelAgent.tags`: `api:chat_completions_only` and
`api:responses_only`. Both are **positive declarations of a proven
restriction**, not additive "this shape works" claims -- an important
distinction the regression above forced into the open. `reasoning_effort_supported`/`stream_usage_supported`
already established the org's precedent of `None`/absent meaning "unproven",
never "known false"; the natural extension for a request-*shape* signal
(where the safe, already-working default is "just pass it through, exactly
as before this ADR") is that **absence of a tag means "unproven and
therefore untouched"**, not "unproven and therefore chat-only." A tag only
ever *adds* a translation step for a provably-incompatible request; it never
*removes* working passthrough from a provider nothing is known about. This
tag namespace (`api:`) is deliberately distinct from the pre-existing
`capability:` prefix, which already means "this model can serve general chat
text at all" -- a *modality* question (`chat_capability.is_general_chat_candidate`)
orthogonal to which wire *shape* an agent's HTTP endpoint accepts.

This still satisfies the product requirement to "default to
chat-completions-compatible... rather than failing closed" for a genuinely
unknown provider: nothing in this mechanism can ever raise or 404 a request
because a shape is undeclared -- an untagged agent gets plain passthrough
(which is not a failure, and is today's actual behavior), and only a
positively-tagged agent is translated. No agent is ever hard-blocked from
serving a request because a capability was never declared.

### API-version data model

`contextual_orchestrator/provider_api_version.py` is a standalone leaf
module (no dependency on `orchestrator.py` or `model_discovery.py`, so
`orchestrator.py` can import it at module load with no circular-import risk)
holding `ProviderApiVersion(header_name, query_param_name, value)` and a
`provider_name -> ProviderApiVersion` registry, `PROVIDER_API_VERSIONS`,
which **ships empty** (see Deferred below). `ModelClient._provider_url` --
the single method every one of the ten outgoing-request builders in this
class already routes its URL construction through -- applies a declared
query parameter automatically via `apply_query_param`; the nine call sites
that build a headers dict (`_send`, `_stream_send`, `_send_raw`,
`proxy_send_bytes`, `proxy_get_bytes`, `proxy_upload`, `_batch_upload`,
`_batch_json`, `_batch_raw`) each gained one line calling `apply_header`,
mirroring the existing per-call-site `format_authorization_header` idiom
those same lines already followed. Lookup is keyed on `agent.provider_name`
-- already a persisted `ModelAgent` field, so no new database column or
migration is needed. This is the same "provider group names are not
hardcoded into routing logic" shape `auth_scheme`/`AUTH_SCHEME_RAW_TOKEN`
already established for Bytez's bare-token Authorization convention: a new
versioned provider is one dict entry, never a new `if provider_name ==
...:` branch in `_send_raw`/`_provider_url`.

## Consequences

- `/v1/chat/completions` and `/v1/responses`, called with a caller-selected
  model that reaches a provider through `ModelClient._proxy_send` (direct
  passthrough, and `_orchestrated_provider_completion`'s final synthesis
  call), now serve a shape-correct response regardless of which shape the
  selected agent's provider natively speaks, without any `server.py` route
  change.
- No agent configured before this ADR changes behavior: the new branches
  fire only for a positively-tagged agent (plus the pre-existing,
  unmodified local-mlx signal).
- **`_proxy_send` is not upstream of every provider call.** `ModelClient.chat()`
  and `ModelClient.stream_chat()` -- used by `route_once`'s worker
  selection, triage, planner calls, and `conduct`'s own intermediate
  evidence-gathering steps, not just the two public passthrough endpoints
  above -- always build and send Chat Completions shape with no translation
  branch of their own. An agent declared `api:responses_only` that gets
  selected through any of those paths would otherwise silently receive a
  shape it is proven not to accept. A follow-up commit on this same PR
  closes that gap by having both methods fail closed (raise `ValueError`)
  for a `responses_only`-tagged agent, rather than building the
  considerably larger live-shape-translation machinery real token streaming
  through those methods would need -- that remains deferred, tracked below.
- Not every field round-trips. Responses' built-in tool-use primitives
  (`web_search_call`, `computer_call`, `mcp_call`/`mcp_list_tools`,
  `image_generation_call`, `local_shell_call`) and reasoning-summary items
  have no Chat Completions equivalent at all; `responses_request_to_chat_request`
  raises `ValueError` for them (unchanged from before this ADR -- ADR 0002's
  own admission that "unsupported Codex namespaces... are not forwarded").
  `responses_response_to_chat_response`, by contrast, never raises on the
  *response* side -- a caller-facing reply must return 200 with whatever
  chat-expressible content the provider produced, not fail the whole
  request over an unmappable reasoning trace.
- Multiple `tool_calls` on one Chat Completions assistant turn become that
  many separate Responses `function_call` items when translated up, which
  loses the fact they originally shared one turn if there was more than
  one. A round trip through both directions preserves every message's text
  content and every tool call's name/arguments/linkage, but not necessarily
  the exact original message *count* -- verified explicitly in
  `tests/test_chat_responses_shape.py`.
- **Deferred: `ModelClient.chat()`/`stream_chat()` fail closed for a
  `responses_only` agent rather than translating.** `route_once`, triage,
  planner calls, `conduct`'s intermediate worker steps, and real
  token-by-token streaming (`stream_route`) all reach a provider through
  these two methods, not `_proxy_send`. Building live translation for them
  -- particularly for `stream_chat`, which would mean re-shaping a
  provider's real-time Responses SSE deltas back into Chat Completions
  deltas as they arrive, not translating one already-complete JSON body --
  is meaningfully more work than this ADR's scope. Until that exists, an
  agent declared `api:responses_only` is usable only through the two public
  passthrough endpoints' non-streaming/`_proxy_send`-routed paths; selecting
  it for general routing raises a clear `ValueError` instead of silently
  sending it a shape it cannot accept.
- **Deferred: Azure OpenAI and native Anthropic are not populated into
  `PROVIDER_API_VERSIONS`, on purpose.** Both motivated this mechanism, and
  the mechanism is ready for them, but onboarding either as a real,
  production-traffic-serving provider needs a separate change this ADR does
  not make:
  - Azure OpenAI genuinely speaks OpenAI-compatible Chat Completions and
    Responses shape (this ADR's translation would apply cleanly), but its
    real authentication convention is a header literally named `api-key`,
    not `Authorization: <scheme> <token>` -- every header-building call
    site in `ModelClient` hardcodes the header name `"authorization"`, a
    different gap than API versioning. `auth_scheme`/`AUTH_SCHEME_RAW_TOKEN`
    already vary the Authorization *value*; varying the header *name* is a
    small, natural extension of that same field, but a distinct piece of
    work.
  - Native Anthropic's `/v1/messages` API is neither Chat Completions nor
    Responses shape -- it is a third wire shape entirely (content blocks,
    `system` as a top-level field, its own tool-use block types, a
    different stop-reason vocabulary). Onboarding it for real needs an
    OpenAI<->Anthropic message-shape translator, which is out of this
    ADR's explicit scope (Chat Completions <-> Responses only), not a
    version-header gap.

  Both header- and query-param-based conventions are instead exercised
  directly in `tests/test_chat_responses_shape.py` (via a monkeypatched
  registry entry, not `PROVIDER_API_VERSIONS` itself), so the mechanism is
  demonstrated and regression-tested against realistic conventions without
  the shipped registry claiming support this PR has not actually verified
  end-to-end.

## References

OpenAI. (n.d.). *Chat Completions API reference*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/chat

OpenAI. (n.d.). *Responses API reference*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/responses

Anthropic. (n.d.). *Versions*. Anthropic API Reference.
https://docs.claude.com/en/api/versioning

Microsoft. (n.d.). *Azure OpenAI Service REST API reference*. Microsoft
Learn. https://learn.microsoft.com/en-us/azure/ai-services/openai/reference
