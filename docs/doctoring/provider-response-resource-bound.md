# Provider response resource-bound evidence

## Decision record

Contextual Orchestrator treats every model-provider response body and its framing metadata as untrusted input. The DNS-pinned transport therefore limits cumulative consumed response bytes to **8 MiB (8,388,608 bytes) per HTTP response** before JSON parsing, batch-output decoding, or server-sent-event processing can continue.

The 8 MiB value is a reviewed product safety bound, not a value mandated by HTTP, OWASP, or Python. It is intentionally high relative to ordinary chat/completion responses while remaining low enough to prevent one provider response from becoming an unbounded memory-consumption surface. Workloads whose legitimate batch output exceeds the bound must be partitioned into smaller batches rather than silently truncating evidence.

## Security and reliability basis

OWASP API4:2023 identifies missing or inappropriate resource limits as a common API weakness with denial-of-service and cost consequences, and recommends explicit bounds on data size and resource consumption. This applies to outbound provider integration as well as inbound APIs because a compromised, malfunctioning, or policy-incompatible upstream can return unexpectedly large data.

RFC 9110 defines the semantics of HTTP response content but does not impose an application-specific maximum representation size. It permits a recipient to normalize repeated `Content-Length` values only when every decimal value is identical, requires invalid or conflicting values to be rejected, and warns that recipients must anticipate potentially large decimal numerals. The application therefore owns both a framing-validation policy and a defensible consumption limit.

Python's `http.client.HTTPResponse.read([amt])` supports reading at most the next requested number of bytes. Contextual Orchestrator uses that primitive to request no more than the remaining response budget plus one byte. The single probe byte distinguishes an exact-limit response from an oversized response without first buffering the complete body. Python's `HTTPResponse.getheader()` combines repeated values with a comma, so the transport parses the complete field value rather than trusting only its first member.

The WHATWG HTML Standard defines the server-sent-event stream format's MIME type as `text/event-stream`, requires UTF-8 encoding, and specifies event-stream line framing. A successful HTTP status alone therefore does not prove that a provider honored the streaming representation contract. A reverse proxy, provider fallback, or incompatible endpoint can return a `200` response with JSON, HTML, or another representation. Contextual Orchestrator requires the normalized response media type to be `text/event-stream` before it consumes a real provider response through the streaming iterator; media-type parameters such as `charset=utf-8` remain compatible.

OpenAI's Chat Completions API additionally defines an OpenAI-compatible streaming terminal contract: streamed chunks are followed by a `data: [DONE]` message, while interruption can prevent final stream metadata from arriving. Contextual Orchestrator therefore treats `[DONE]` as positive completion evidence for an accepted OpenAI-compatible SSE response instead of treating transport EOF as successful model completion.

## Runtime contract

`contextual_orchestrator.provider_transport._ProviderHTTPResponse` owns the bound for every existing `ModelClient` provider path. No caller-specific opt-in is required.

The contract is:

1. a declared `Content-Length` greater than the remaining 8 MiB response budget is rejected before any body byte is read;
2. repeated comma-separated `Content-Length` members are accepted only when their ASCII decimal values are canonically equal, including harmless leading-zero differences, with only HTTP optional whitespace (`SP` or `HTAB`) removed around each member;
3. empty, signed, fractional, non-ASCII, non-HTTP-whitespace, malformed, or conflicting `Content-Length` evidence fails closed;
4. simultaneous `Content-Length` and `Transfer-Encoding` evidence is rejected as ambiguous rather than selecting a preferred framing interpretation;
5. decimal lengths are compared as canonical strings instead of converting an attacker-controlled numeral into an unbounded integer;
6. absent `Content-Length` remains supported and is still governed by cumulative consumption accounting;
7. ordinary `read()` calls request at most the remaining budget plus one byte;
8. explicit smaller reads preserve the caller's requested size;
9. explicit negative or over-budget reads are reduced to the remaining budget plus one byte;
10. cumulative reads share one budget for the lifetime of the response wrapper;
11. real `http.client.HTTPResponse` iteration is treated as provider streaming and requires a normalized `Content-Type` media type of exactly `text/event-stream` before any body line is consumed;
12. `text/event-stream` parameters are accepted after media-type normalization, while missing or different media types fail closed instead of producing an empty or misframed successful stream;
13. real provider streaming uses size-limited `readline()` calls so a single pathological SSE line cannot bypass the bound before inspection;
14. an accepted SSE response is successful only when its OpenAI-compatible terminal `data: [DONE]` marker is consumed;
15. JSON-malformed `data:` frames fail closed instead of being silently discarded;
16. EOF before `[DONE]` fails closed instead of converting a truncated model answer into successful orchestration evidence;
17. lightweight non-HTTP test doubles retain ordinary iteration while receiving the same cumulative accounting;
18. exceeding 8 MiB raises a non-transient runtime failure rather than returning truncated content; and
19. constructor-time framing rejection and context-managed consumption failure both close the response and direct provider connection deterministically.

The header preflight is an optimization and an early rejection boundary, not proof that the eventual body is trustworthy or complete. A provider can omit or misstate its declared length, so every accepted response remains subject to the authoritative cumulative byte counter.

This boundary applies uniformly to chat responses, raw OpenAI-compatible passthrough, batch metadata, batch result downloads, and SSE streaming because those paths all consume the same response wrapper. Ordinary JSON and batch-response bodies use bounded `read()` and retain their existing completion semantics. Real HTTP response iteration is reserved for the provider-streaming path and therefore requires `text/event-stream` plus `[DONE]` completion evidence.

## Failure semantics

Oversize provider content, invalid or ambiguous framing, and an incompatible provider-stream media type are not retried as transient network errors. Retrying the same policy-invalid representation would amplify provider load, duplicate spend, and resource consumption without changing the violated contract.

Framing-header and stream-media-type header access failures become stable redacted runtime errors. Provider-controlled exception text is not exposed to callers or logs through this boundary. Cleanup is attempted by the response context manager, and cleanup failure cannot convert the invalid provider response into successful orchestration evidence.

The service does not publish partial JSON, partial batch evidence, or a partial streamed line after the byte budget is exceeded. A wrong or missing streaming media type is rejected before the first body line is consumed. For a valid live SSE connection, deltas delivered before a later malformed frame or premature EOF cannot be recalled from an already-reading client. The provider stream nevertheless fails rather than being persisted as a successful route, and the HTTP streaming surface can terminate with its existing error semantics instead of presenting the truncated provider response as complete.

A malformed provider `data:` payload is reported through a stable redacted runtime error; provider-controlled parser detail is not exposed through this boundary. Premature EOF is likewise reported as an incomplete provider stream rather than accepted as implicit completion.

## Verification contract

`tests/test_provider_response_bounds.py` preserves the resource-bound regression surface. `tests/test_true_streaming.py` preserves the provider-stream completion and media-type regression surface. Together they prove:

- the reviewed default is exactly 8 MiB;
- invalid byte budgets fail closed;
- over-budget declared lengths fail before a body read;
- equal repeated decimal lengths, including leading-zero equivalents and valid `SP`/`HTAB` optional whitespace, remain valid;
- malformed, non-ASCII, vertical/form-feed whitespace, non-breaking-space, and conflicting declared lengths fail closed;
- `Content-Length` plus `Transfer-Encoding` fails as ambiguous;
- framing-header lookup failures are redacted and close both resources;
- an unbounded read probes only one byte beyond the remaining budget;
- bodies exactly at the limit remain valid;
- repeated explicit reads cannot bypass cumulative accounting;
- negative full-read semantics remain bounded;
- valid `text/event-stream` responses, including media-type parameters, use bounded `readline()` calls;
- a `200` provider response with a non-event-stream media type is rejected instead of masquerading as a successful stream;
- stream `Content-Type` lookup failure is redacted and closes response and connection resources;
- cumulative streaming overflow fails;
- a normal provider SSE sequence preserves live content deltas and accepts `[DONE]` completion;
- malformed provider `data:` JSON fails closed;
- EOF before `[DONE]` fails closed after any previously delivered deltas; and
- response and connection cleanup still occurs when framing or consumption validation fails.

The streaming media-type regression is test-first: commit `f4f650734aa0bad856b3e4389d63de45d0e52e76` adds the wrong-media-type failure contract before production commit `529182d9186fd353cb1cd44e08f9483c39520cad` enforces it. The earlier SSE-completion and response-bound test-only commits likewise precede their production implementations. Focused deterministic tests require no provider credential or public network egress. Repository and central exact-head gates remain separately authoritative.

## Operational and compatibility notes

The bound and media-type validation are intentionally enforced below model- or provider-specific parsing so malformed content cannot claim a larger allowance or a successful streaming interpretation by choosing another response shape. No provider identity, model-routing policy, reviewer credential, or authority boundary changes.

A provider that sends both `Content-Length` and `Transfer-Encoding`, conflicting repeated lengths, non-decimal length evidence, whitespace outside HTTP `SP`/`HTAB`, a missing or non-`text/event-stream` streaming media type, malformed OpenAI-compatible SSE `data:` JSON, or an SSE connection that ends without `[DONE]` is treated as incompatible or incomplete. Operators should preserve the bounded failure, retain the provider and endpoint identity in redacted incident evidence, and correct or replace the upstream integration rather than adding a local parsing exception.

If production evidence shows a legitimate response class consistently approaching 8 MiB, raise a separately reviewed change with workload measurements and an explicit threat-model update. Do not disable the bound locally, truncate silently, or add an unreviewed environment-variable bypass. Likewise, do not reinterpret a JSON/HTML `200` response or transport EOF as successful OpenAI-compatible streaming completion merely to accommodate an incompatible provider; such compatibility must be a separately reviewed protocol contract with explicit provider isolation.

## Rollback

If a compatibility regression is discovered, revert the framing-preflight and bounded-response commits as reviewed units and preserve the prior DNS-pinning, TLS identity, redirect, proxy-isolation, and cleanup controls. If the SSE media-type or completion hardening must be reverted separately, keep the byte budget intact and document which provider contract cannot emit the standard `text/event-stream` representation or OpenAI-compatible terminal marker. A rollback is not authorization to introduce an unbounded alternative transport, accept ambiguous HTTP framing, or silently bless a non-stream representation or partial model output as complete.

## APA 7 references

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics* (RFC 9110; STD 97). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110.html

OpenAI. (n.d.). *Chat Completions*. OpenAI API Reference. Retrieved August 8, 2026, from https://platform.openai.com/docs/api-reference/chat

OWASP Foundation. (2023). *API4:2023 unrestricted resource consumption*. OWASP API Security Top 10. https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/

Python Software Foundation. (2026). *http.client — HTTP protocol client*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/http.client.html

WHATWG. (2026, July 20). *HTML Standard, Edition for Web Developers: Server-sent events*. https://html.spec.whatwg.org/dev/server-sent-events.html
