# Graph Report - token-scope-current-input  (2026-09-13)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 409 nodes · 1024 edges · 26 communities (25 shown, 1 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 11 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d555ec4a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25

## God Nodes (most connected - your core abstractions)
1. `RequestError` - 116 edges
2. `do_POST()` - 103 edges
3. `build_server()` - 59 edges
4. `SecurityConfig` - 39 edges
5. `_coerce_optional_bool()` - 23 edges
6. `_validate_chat_sampling_and_control_fields()` - 22 edges
7. `_coerce_optional_int()` - 19 edges
8. `do_GET()` - 16 edges
9. `_non_omit_object_entries()` - 10 edges
10. `_stream_route_completion()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `test_http_preserves_caller_generation_limit()` --uses--> `SecurityConfig`  [INFERRED]
  tests/test_generation_token_ingress.py → contextual_orchestrator/server.py
- `_server()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_chat_max_completion_tokens_http_honesty.py → contextual_orchestrator/server.py
- `_server()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_completions_max_completion_tokens_http_honesty.py → contextual_orchestrator/server.py
- `test_http_max_tokens_applies_and_restores()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_completions_max_tokens_http_honesty.py → contextual_orchestrator/server.py
- `test_http_rejects_bool_max_tokens()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_completions_max_tokens_http_honesty.py → contextual_orchestrator/server.py

## Import Cycles
- None detected.

## Communities (26 total, 1 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.08
Nodes (52): build_server(), _admin_purpose(), _audit_trace_disclosure(), _authorize(), _authorize_trace_access(), _begin_sse(), _write(), _bind_session() (+44 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (35): _coerce_optional_bool(), HTTP server exposing chat, admin, governance, and evaluation endpoints., Legacy Completions ``echo`` — boolean / JS 0/1; ``true`` is not supported.…, Responses ``logprobs`` / ``top_logprobs`` — OpenAI shape; invalid fail closed.…, Responses ``parallel_tool_calls`` — strict boolean when present. OpenAI uses…, Legacy Completions ``logprobs`` — token logprobs are not supported. This…, Legacy Completions ``stream_options`` — object with boolean flags; requires…, Chat Completions ``stream_options`` — validate supported streaming flags. Shape… (+27 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (32): _coerce_logit_bias_token_key(), _coerce_logit_bias_value(), _coerce_optional_float(), Coerce a logit_bias map value to float in [-100, 100]. Accepts int/float and…, Normalize a logit_bias map key to a digit token id string. Form/JS SDKs often…, Legacy Completions ``logit_bias`` — empty object is a no-op; non-empty fails…, OpenAI ``service_tier`` — known tier names are no-ops; unknown fail closed.…, OpenAI ``user`` end-user id — optional string, max 64 characters. Explicit JSON… (+24 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (28): _cache_partition(), do_POST(), _validate_trace_request(), _cache_bypass_header(), _chat_usage_measurement_payload(), _multipart_upload_metadata(), Read purpose, filename, and file length from a seekable multipart body., Responses ``stop`` — string or ≤4 non-empty strings (≤256 chars); pass through.… (+20 more)

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (23): Any, _chat_response_sse_chunks(), Validate or default the chat/completions model. An omitted ``model`` selects…, Validate the naruon request policy without treating it as provider input., Responses ``stream_options`` — not supported (Responses streaming is off).…, Fail closed on role=tool messages missing a usable tool_call_id. Runs before…, Reject response_format on legacy Completions with a migration path. Structured…, Responses ``modalities`` — omit or ``["text"]`` only (text gateway). (+15 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (24): _coerce_optional_int(), Responses ``n`` — only omit or 1; multi-choice is not framed on passthrough.…, Responses ``seed`` — signed int64; valid values pass through to the provider.…, Legacy Completions ``seed`` — type-checked then rejected (not applied). OpenAI…, Validate legacy Completions ``max_tokens`` as a positive integer., Validate Chat Completions ``max_completion_tokens`` as a positive integer.…, Responses ``max_output_tokens`` — OpenAI-native output budget (positive int).…, Reject ``max_tool_calls`` — no multi-step tool loop on this gateway. OpenAI may… (+16 more)

### Community 6 - "Community 6"
Cohesion: 0.10
Nodes (21): _read_json(), _coerce_json(), Validate the required trust-boundary fields for media/rerank passthrough., OpenAI assistant ``tool_calls`` array shape on chat messages. Each entry must…, OpenAI ``metadata`` — object of string pairs, at most 16 entries. Keys must be…, HTTP-safe request failure., Return a safe JSON body length or reject ambiguous HTTP framing. The stdlib…, Reject modern OpenAI SDK control fields not applied on this gateway.… (+13 more)

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (9): Runtime safety controls for the stdlib HTTP server., Require explicit opt-in before binding the API to public interfaces., Return the bearer value when the Authorization header has the expected shape., Revoke one opaque admin session without retaining the bearer., Apply a simple per-client fixed-window request budget., Reserve a run slot, rejecting quickly when the process is saturated., Release a run slot acquired by acquire_run_slot., Return a secret-free security profile for sales-readiness evidence. (+1 more)

### Community 8 - "Community 8"
Cohesion: 0.16
Nodes (16): _coerce_embedding_token_sequence(), _coerce_token_id(), _embedding_token_sequence_to_text(), _is_embedding_token_sequence(), _is_token_id_shaped(), _normalize_embedding_input_item(), True for numeric token-id shapes (int / whole float), including negatives and…, Coerce one non-negative OpenAI token id, or None if not a valid token id.… (+8 more)

### Community 9 - "Community 9"
Cohesion: 0.12
Nodes (16): _non_omit_object_entries(), Reject chat-era modalities/prediction/reasoning_effort on Completions. Legacy…, Drop nested null / blank / empty-object entries (SDK optional defaults). Parity…, Reject ``audio`` / ``web_search_options`` with named migration errors. This…, Reject Assistants-style ``tool_resources`` with a named unsupported error.…, Reject Responses-style ``reasoning`` object on chat Completions. OpenAI…, Reject Responses-style ``reasoning`` object on legacy Completions. Explicit…, Responses ``prediction`` (Predicted Outputs) — not supported on this gateway.… (+8 more)

### Community 10 - "Community 10"
Cohesion: 0.15
Nodes (13): BatchRequest, _embeddings_attribution(), OpenAI multimodal content-parts array (text + image_url) for vision callers.…, Fail closed on chat message keys outside the OpenAI surface we honor. Named…, Reject unknown message keys and legacy function role before passthrough., Build ledger attribution from the explicit ``attribution`` field merged with…, _reject_unknown_message_keys(), _validate_attribution() (+5 more)

### Community 11 - "Community 11"
Cohesion: 0.32
Nodes (12): build(), _post(), TaskOrchestrator, Chat Completions max_completion_tokens honesty over HTTP (budget precedence)., When both budgets are present, request must still succeed (max_completion wins)., _server(), test_http_chat_accepts_max_completion_tokens(), test_http_chat_accepts_max_completion_tokens_omitted() (+4 more)

### Community 12 - "Community 12"
Cohesion: 0.33
Nodes (11): build(), _post(), TaskOrchestrator, Responses max_output_tokens (OpenAI-native budget) honesty over HTTP., Official Responses clients send max_output_tokens — must not be unknown_fields., _server(), test_http_responses_accepts_omit_max_output_tokens(), test_http_responses_accepts_valid_max_output_tokens() (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.38
Nodes (10): build(), _post(), TaskOrchestrator, Completions max_completion_tokens honesty over HTTP (chat-era alias)., _server(), test_http_completions_accepts_max_completion_tokens(), test_http_completions_prefers_max_completion_tokens_over_max_tokens(), test_http_completions_rejects_non_integer_max_completion_tokens() (+2 more)

### Community 14 - "Community 14"
Cohesion: 0.38
Nodes (10): build(), _post(), TaskOrchestrator, Responses max_tokens / max_completion_tokens honesty over HTTP (fail-closed)., _server(), test_http_responses_accepts_valid_max_completion_tokens(), test_http_responses_accepts_valid_max_tokens(), test_http_responses_rejects_boolean_max_completion_tokens() (+2 more)

### Community 15 - "Community 15"
Cohesion: 0.22
Nodes (9): _is_omit_equivalent_list(), Fail closed on OpenAI conversation-control fields this gateway does not apply.…, True when list is empty or every item is null / blank string., Keep file inputs and provider-only controls on the preserving path., Reject OpenAI ``include`` outside Responses (where it is also unsupported).…, _responses_virtual_requires_provider_path(), contains_file(), _validate_chat_include_field() (+1 more)

### Community 16 - "Community 16"
Cohesion: 0.22
Nodes (5): register_video_job(), Return a stable non-secret owner key for the authenticated deployment principal., Hash a stable deployment principal without retaining bearer material., Return the opaque admin session id from the request cookie, if present., Reject cross-origin state changes authenticated only by a session cookie.

### Community 17 - "Community 17"
Cohesion: 0.44
Nodes (8): build(), _post(), TaskOrchestrator, Completions max_tokens is applied to the provider client for the request., test_http_max_tokens_applies_and_restores(), test_http_rejects_bool_max_tokens(), test_http_rejects_non_positive_max_tokens(), test_http_without_max_tokens_ok()

### Community 18 - "Community 18"
Cohesion: 0.25
Nodes (8): _coerce_tool_function_strict(), _omit_null_tool_function_field(), Drop a JSON-null optional ``tool.function`` field or fail-closed. Official…, Null/empty omit; bool and form/JS 0/1/"true" forms coerce for ``strict``., Shared name/description/parameters/strict checks for chat or flat tools., OpenAI chat/Responses ``tools`` — nested or flat function tool objects. Empty…, _validate_chat_tools(), _validate_tool_function_fields()

### Community 19 - "Community 19"
Cohesion: 0.39
Nodes (5): Serve slow upstream calls concurrently without a five-connection backlog.…, Stop accepting requests and release embedding worker threads., Close the listener and workers on normal or abnormal serve exit., ResponsiveThreadingHTTPServer, ThreadingHTTPServer

### Community 20 - "Community 20"
Cohesion: 0.29
Nodes (4): parametrize, Generation limits remain caller values at the model execution boundary., A boundary fixture above the former cap does not claim real model capacity., test_http_preserves_caller_generation_limit()

### Community 21 - "Community 21"
Cohesion: 0.33
Nodes (3): Compare UTF-8 secret bytes without leaking non-ASCII failures., Mint a bounded opaque session after validating the admin credential., Remove expired sessions while the caller holds the session lock.

### Community 22 - "Community 22"
Cohesion: 0.33
Nodes (3): Resolve and validate the route-owned purpose for an authenticated role., Validate a bearer token or an opaque admin session; return the authorized…, Return whether an opaque session exists and has not expired.

### Community 23 - "Community 23"
Cohesion: 0.50
Nodes (4): _encode_embedding_base64(), _openai_embeddings_response(), OpenAI base64 embedding: little-endian float32 binary, ASCII base64., Map batch document vectors to the OpenAI ``/v1/embeddings`` list shape.

### Community 24 - "Community 24"
Cohesion: 0.50
Nodes (4): Collect stripped tool names from nested or flat ``tools`` entries., OpenAI chat/Responses ``tool_choice`` — none/auto/required or named function.…, _tool_choice_declared_names(), _validate_chat_tool_choice()

## Knowledge Gaps
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build_server()` connect `Community 0` to `Community 1`, `Community 3`, `Community 4`, `Community 6`, `Community 7`, `Community 11`, `Community 12`, `Community 13`, `Community 14`, `Community 17`, `Community 19`, `Community 20`?**
  _High betweenness centrality (0.178) - this node is a cross-community bridge._
- **Why does `RequestError` connect `Community 6` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 15`, `Community 16`, `Community 18`, `Community 21`, `Community 22`, `Community 24`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Why does `do_POST()` connect `Community 3` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 6`, `Community 8`, `Community 9`, `Community 10`, `Community 15`, `Community 16`, `Community 18`, `Community 23`, `Community 24`?**
  _High betweenness centrality (0.124) - this node is a cross-community bridge._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.07518796992481203 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.07807807807807808 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.07258064516129033 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.07142857142857142 - nodes in this community are weakly interconnected._