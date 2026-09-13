# Graph Report - token-scope-evidence  (2026-09-13)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 403 nodes · 1006 edges · 28 communities (22 shown, 6 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 11 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `012beaac`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- do_POST
- _validate_chat_sampling_and_control_fields
- RequestError
- _coerce_optional_bool
- _coerce_optional_int
- server.py
- Any
- _non_omit_object_entries
- SecurityConfig
- _validate_embeddings_inputs
- test_chat_max_completion_tokens_http_honesty.py
- .principal_id
- test_responses_max_output_tokens_http_honesty.py
- _validate_responses_conversation_controls
- test_responses_max_tokens_http_honesty.py
- test_completions_max_completion_tokens_http_honesty.py
- _validate_tool_function_fields
- ResponsiveThreadingHTTPServer
- .establish_admin_session
- _validate_messages
- test_http_preserves_caller_generation_limit
- _validate_chat_tool_choice
- .admin_session_clear_cookie_header
- _validate_openai_sdk_control_fields
- responses_sse_body
- _validate_responses_logprobs
- _validate_completions_stream_options
- _validate_responses_store

## God Nodes (most connected - your core abstractions)
1. `RequestError` - 116 edges
2. `do_POST()` - 103 edges
3. `build_server()` - 54 edges
4. `SecurityConfig` - 34 edges
5. `_coerce_optional_bool()` - 23 edges
6. `_validate_chat_sampling_and_control_fields()` - 22 edges
7. `_coerce_optional_int()` - 19 edges
8. `do_GET()` - 16 edges
9. `_server()` - 11 edges
10. `_non_omit_object_entries()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `test_http_preserves_caller_generation_limit()` --uses--> `SecurityConfig`  [INFERRED]
  tests/test_generation_token_ingress.py → contextual_orchestrator/server.py
- `_server()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_chat_max_completion_tokens_http_honesty.py → contextual_orchestrator/server.py
- `_server()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_completions_max_completion_tokens_http_honesty.py → contextual_orchestrator/server.py
- `_server()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_responses_max_output_tokens_http_honesty.py → contextual_orchestrator/server.py
- `_server()` --calls--> `SecurityConfig`  [EXTRACTED]
  tests/test_responses_max_tokens_http_honesty.py → contextual_orchestrator/server.py

## Import Cycles
- None detected.

## Communities (28 total, 6 thin omitted)

### Community 0 - "do_POST"
Cohesion: 0.08
Nodes (56): build_server(), _admin_purpose(), _audit_trace_disclosure(), _authorize(), _authorize_trace_access(), _begin_sse(), _write(), _bind_session() (+48 more)

### Community 1 - "_validate_chat_sampling_and_control_fields"
Cohesion: 0.07
Nodes (32): _coerce_logit_bias_token_key(), _coerce_logit_bias_value(), _coerce_optional_float(), Coerce a logit_bias map value to float in [-100, 100]. Accepts int/float and…, Normalize a logit_bias map key to a digit token id string. Form/JS SDKs often…, Legacy Completions ``logit_bias`` — empty object is a no-op; non-empty fails…, OpenAI ``service_tier`` — known tier names are no-ops; unknown fail closed.…, OpenAI ``user`` end-user id — optional string, max 64 characters. Explicit JSON… (+24 more)

### Community 2 - "RequestError"
Cohesion: 0.08
Nodes (29): _read_json(), _cache_bypass_header(), _coerce_json(), Fail closed when ``model_name`` is not served by any enabled agent. OpenAI…, Message-level ``audio`` / ``function_call`` — null/empty omit; else fail…, Fail closed on role=tool messages missing a usable tool_call_id. Runs before…, OpenAI ``metadata`` — object of string pairs, at most 16 entries. Keys must be…, HTTP-safe request failure. (+21 more)

### Community 3 - "_coerce_optional_bool"
Cohesion: 0.07
Nodes (26): _coerce_optional_bool(), Legacy Completions ``echo`` — boolean / JS 0/1; ``true`` is not supported.…, Responses ``parallel_tool_calls`` — strict boolean when present. OpenAI uses…, Legacy Completions ``logprobs`` — token logprobs are not supported. This…, Chat Completions ``stream_options`` — validate supported streaming flags. Shape…, Fail-closed chat ``logprobs`` / ``top_logprobs`` before any proxy. Chat route…, OpenAI-adjacent routing hints for sync vs batch channel selection. Fail closed…, Chat Completions ``store`` — strict boolean; ``true`` is not supported. OpenAI… (+18 more)

### Community 4 - "_coerce_optional_int"
Cohesion: 0.09
Nodes (24): _coerce_optional_int(), Legacy Completions ``n`` — positive integer; only ``n=1`` is supported. OpenAI…, Responses ``n`` — only omit or 1; multi-choice is not framed on passthrough.…, Responses ``seed`` — signed int64; valid values pass through to the provider.…, Validate legacy Completions ``max_tokens`` as a positive integer., Validate Chat Completions ``max_completion_tokens`` as a positive integer.…, Responses ``max_output_tokens`` — OpenAI-native output budget (positive int).…, Reject ``max_tool_calls`` — no multi-step tool loop on this gateway. OpenAI may… (+16 more)

### Community 5 - "server.py"
Cohesion: 0.10
Nodes (21): _chat_usage_measurement_payload(), HTTP server exposing chat, admin, governance, and evaluation endpoints., Responses ``stop`` — string or ≤4 non-empty strings (≤256 chars); pass through.…, Legacy Completions ``suffix`` — optional string; non-empty is not supported.…, Validate the required trust-boundary fields for media/rerank passthrough., OpenAI assistant ``tool_calls`` array shape on chat messages. Each entry must…, Validate or auto-select an OpenAI embeddings model. Strip + write back (parity…, OpenAI ``encoding_format`` — omit/null/empty, ``float``, or ``base64``.… (+13 more)

### Community 6 - "Any"
Cohesion: 0.11
Nodes (21): Any, BatchRequest, _chat_response_sse_chunks(), _embeddings_attribution(), _multipart_upload_metadata(), Read purpose, filename, and file length from a seekable multipart body., Validate or default the chat/completions model. An omitted ``model`` selects…, Validate or default the Chat Completions model. Chat exposes the advertised… (+13 more)

### Community 7 - "_non_omit_object_entries"
Cohesion: 0.09
Nodes (20): _encode_embedding_base64(), _non_omit_object_entries(), _openai_embeddings_response(), Reject chat-era modalities/prediction/reasoning_effort on Completions. Legacy…, Drop nested null / blank / empty-object entries (SDK optional defaults). Parity…, Reject ``audio`` / ``web_search_options`` with named migration errors. This…, Reject Assistants-style ``tool_resources`` with a named unsupported error.…, Reject Responses-style ``reasoning`` object on chat Completions. OpenAI… (+12 more)

### Community 8 - "SecurityConfig"
Cohesion: 0.12
Nodes (9): Runtime safety controls for the stdlib HTTP server., Require explicit opt-in before binding the API to public interfaces., Return the bearer value when the Authorization header has the expected shape., Revoke one opaque admin session without retaining the bearer., Apply a simple per-client fixed-window request budget., Reserve a run slot, rejecting quickly when the process is saturated., Release a run slot acquired by acquire_run_slot., Return a secret-free security profile for sales-readiness evidence. (+1 more)

### Community 9 - "_validate_embeddings_inputs"
Cohesion: 0.16
Nodes (16): _coerce_embedding_token_sequence(), _coerce_token_id(), _embedding_token_sequence_to_text(), _is_embedding_token_sequence(), _is_token_id_shaped(), _normalize_embedding_input_item(), True for numeric token-id shapes (int / whole float), including negatives and…, Coerce one non-negative OpenAI token id, or None if not a valid token id.… (+8 more)

### Community 10 - "test_chat_max_completion_tokens_http_honesty.py"
Cohesion: 0.31
Nodes (13): build(), _post(), TaskOrchestrator, Chat Completions max_completion_tokens honesty over HTTP (budget precedence)., When both budgets are present, request must still succeed (max_completion wins)., _server(), test_http_chat_accepts_max_completion_tokens(), test_http_chat_accepts_max_completion_tokens_omitted() (+5 more)

### Community 11 - ".principal_id"
Cohesion: 0.17
Nodes (7): register_video_job(), Resolve and validate the route-owned purpose for an authenticated role., Validate a bearer token or an opaque admin session; return the authorized…, Return a stable non-secret owner key for the authenticated deployment principal., Return the opaque admin session id from the request cookie, if present., Return whether an opaque session exists and has not expired., Reject cross-origin state changes authenticated only by a session cookie.

### Community 12 - "test_responses_max_output_tokens_http_honesty.py"
Cohesion: 0.32
Nodes (12): build(), _post(), TaskOrchestrator, Responses max_output_tokens (OpenAI-native budget) honesty over HTTP., Official Responses clients send max_output_tokens — must not be unknown_fields., _server(), test_http_responses_accepts_omit_max_output_tokens(), test_http_responses_accepts_valid_max_output_tokens() (+4 more)

### Community 13 - "_validate_responses_conversation_controls"
Cohesion: 0.18
Nodes (11): _is_omit_equivalent_list(), Official Responses ``text`` — ``format`` shapes, omit-real optionals. Official…, Fail closed on OpenAI conversation-control fields this gateway does not apply.…, True when list is empty or every item is null / blank string., Keep file inputs and provider-only controls on the preserving path., Reject OpenAI ``include`` outside Responses (where it is also unsupported).…, _responses_virtual_requires_provider_path(), contains_file() (+3 more)

### Community 14 - "test_responses_max_tokens_http_honesty.py"
Cohesion: 0.36
Nodes (11): build(), _post(), TaskOrchestrator, Responses max_tokens / max_completion_tokens honesty over HTTP (fail-closed)., _server(), test_http_responses_accepts_valid_max_completion_tokens(), test_http_responses_accepts_valid_max_tokens(), test_http_responses_rejects_boolean_max_completion_tokens() (+3 more)

### Community 15 - "test_completions_max_completion_tokens_http_honesty.py"
Cohesion: 0.38
Nodes (10): build(), _post(), TaskOrchestrator, Completions max_completion_tokens honesty over HTTP (chat-era alias)., _server(), test_http_completions_accepts_max_completion_tokens(), test_http_completions_prefers_max_completion_tokens_over_max_tokens(), test_http_completions_rejects_non_integer_max_completion_tokens() (+2 more)

### Community 16 - "_validate_tool_function_fields"
Cohesion: 0.25
Nodes (8): _coerce_tool_function_strict(), _omit_null_tool_function_field(), Drop a JSON-null optional ``tool.function`` field or fail-closed. Official…, Null/empty omit; bool and form/JS 0/1/"true" forms coerce for ``strict``., Shared name/description/parameters/strict checks for chat or flat tools., OpenAI chat/Responses ``tools`` — nested or flat function tool objects. Empty…, _validate_chat_tools(), _validate_tool_function_fields()

### Community 17 - "ResponsiveThreadingHTTPServer"
Cohesion: 0.39
Nodes (5): Serve slow upstream calls concurrently without a five-connection backlog.…, Stop accepting requests and release embedding worker threads., Close the listener and workers on normal or abnormal serve exit., ResponsiveThreadingHTTPServer, ThreadingHTTPServer

### Community 18 - ".establish_admin_session"
Cohesion: 0.25
Nodes (4): Compare UTF-8 secret bytes without leaking non-ASCII failures., Hash a stable deployment principal without retaining bearer material., Mint a bounded opaque session after validating the admin credential., Remove expired sessions while the caller holds the session lock.

### Community 19 - "_validate_messages"
Cohesion: 0.29
Nodes (7): OpenAI multimodal content-parts array (text + image_url) for vision callers.…, Fail closed on chat message keys outside the OpenAI surface we honor. Named…, Reject unknown message keys and legacy function role before passthrough., _reject_unknown_message_keys(), _validate_chat_message_known_fields(), _validate_message_content_parts(), _validate_messages()

### Community 20 - "test_http_preserves_caller_generation_limit"
Cohesion: 0.29
Nodes (4): parametrize, Generation limits remain caller values at the model execution boundary., A boundary fixture above the former cap does not claim real model capacity., test_http_preserves_caller_generation_limit()

### Community 21 - "_validate_chat_tool_choice"
Cohesion: 0.50
Nodes (4): Collect stripped tool names from nested or flat ``tools`` entries., OpenAI chat/Responses ``tool_choice`` — none/auto/required or named function.…, _tool_choice_declared_names(), _validate_chat_tool_choice()

## Knowledge Gaps
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build_server()` connect `do_POST` to `RequestError`, `server.py`, `Any`, `SecurityConfig`, `test_chat_max_completion_tokens_http_honesty.py`, `test_responses_max_output_tokens_http_honesty.py`, `test_responses_max_tokens_http_honesty.py`, `test_completions_max_completion_tokens_http_honesty.py`, `ResponsiveThreadingHTTPServer`, `test_http_preserves_caller_generation_limit`?**
  _High betweenness centrality (0.170) - this node is a cross-community bridge._
- **Why does `RequestError` connect `RequestError` to `do_POST`, `_validate_chat_sampling_and_control_fields`, `_coerce_optional_bool`, `_coerce_optional_int`, `server.py`, `Any`, `_non_omit_object_entries`, `SecurityConfig`, `_validate_embeddings_inputs`, `.principal_id`, `_validate_responses_conversation_controls`, `_validate_tool_function_fields`, `.establish_admin_session`, `_validate_messages`, `_validate_chat_tool_choice`, `_validate_openai_sdk_control_fields`, `_validate_responses_logprobs`, `_validate_completions_stream_options`, `_validate_responses_store`?**
  _High betweenness centrality (0.139) - this node is a cross-community bridge._
- **Why does `do_POST()` connect `do_POST` to `_validate_chat_sampling_and_control_fields`, `RequestError`, `_coerce_optional_bool`, `_coerce_optional_int`, `server.py`, `Any`, `_non_omit_object_entries`, `_validate_embeddings_inputs`, `.principal_id`, `_validate_responses_conversation_controls`, `_validate_tool_function_fields`, `_validate_messages`, `_validate_chat_tool_choice`, `_validate_openai_sdk_control_fields`, `_validate_responses_logprobs`, `_validate_completions_stream_options`, `_validate_responses_store`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Should `do_POST` be split into smaller, more focused modules?**
  _Cohesion score 0.07704918032786885 - nodes in this community are weakly interconnected._
- **Should `_validate_chat_sampling_and_control_fields` be split into smaller, more focused modules?**
  _Cohesion score 0.07258064516129033 - nodes in this community are weakly interconnected._
- **Should `RequestError` be split into smaller, more focused modules?**
  _Cohesion score 0.07586206896551724 - nodes in this community are weakly interconnected._
- **Should `_coerce_optional_bool` be split into smaller, more focused modules?**
  _Cohesion score 0.07407407407407407 - nodes in this community are weakly interconnected._