# Provider response resource-bound evidence

## Decision record

Contextual Orchestrator treats every model-provider response body and its framing metadata as untrusted input. The DNS-pinned transport therefore limits cumulative consumed response bytes to **8 MiB (8,388,608 bytes) per HTTP response** before JSON parsing, batch-output decoding, or server-sent-event processing can continue.

The 8 MiB value is a reviewed product safety bound, not a value mandated by HTTP, OWASP, or Python. It is intentionally high relative to ordinary chat/completion responses while remaining low enough to prevent one provider response from becoming an unbounded memory-consumption surface. Workloads whose legitimate batch output exceeds the bound must be partitioned into smaller batches rather than silently truncating evidence.

## Security and reliability basis

OWASP API4:2023 identifies missing or inappropriate resource limits as a common API weakness with denial-of-service and cost consequences, and recommends explicit bounds on data size and resource consumption. This applies to outbound provider integration as well as inbound APIs because a compromised, malfunctioning, or policy-incompatible upstream can return unexpectedly large data.

RFC 9110 defines the semantics of HTTP response content but does not impose an application-specific maximum representation size. It permits a recipient to normalize repeated `Content-Length` values only when every decimal value is identical, requires invalid or conflicting values to be rejected, and warns that recipients must anticipate potentially large decimal numerals. The application therefore owns both a framing-validation policy and a defensible consumption limit.

Python's `http.client.HTTPResponse.read([amt])` supports reading at most the next requested number of bytes. Contextual Orchestrator uses that primitive to request no more than the remaining response budget plus one byte. The single probe byte distinguishes an exact-limit response from an oversized response without first buffering the complete body. Python's `HTTPResponse.getheader()` combines repeated values with a comma, so the transport parses the complete field value rather than trusting only its first member.

## Runtime contract

`contextual_orchestrator.provider_transport._ProviderHTTPResponse` owns the bound for every existing `ModelClient` provider path. No caller-specific opt-in is required.

The contract is:

1. a declared `Content-Length` greater than the remaining 8 MiB response budget is rejected before any body byte is read;
2. repeated comma-separated `Content-Length` members are accepted only when their ASCII decimal values are canonically equal, including harmless leading-zero differences;
3. empty, signed, fractional, non-ASCII, malformed, or conflicting `Content-Length` evidence fails closed;
4. simultaneous `Content-Length` and `Transfer-Encoding` evidence is rejected as ambiguous rather than selecting a preferred framing interpretation;
5. decimal lengths are compared as canonical strings instead of converting an attacker-controlled numeral into an unbounded integer;
6. absent `Content-Length` remains supported and is still governed by cumulative consumption accounting;
7. ordinary `read()` calls request at most the remaining budget plus one byte;
8. explicit smaller reads preserve the caller's requested size;
9. explicit negative or over-budget reads are reduced to the remaining budget plus one byte;
10. cumulative reads share one budget for the lifetime of the response wrapper;
11. real `http.client.HTTPResponse` iteration uses size-limited `readline()` calls so a single pathological SSE line cannot bypass the bound before inspection;
12. lightweight non-HTTP test doubles retain ordinary iteration while receiving the same cumulative accounting;
13. exceeding 8 MiB raises a non-transient runtime failure rather than returning truncated content; and
14. constructor-time framing rejection and context-managed consumption failure both close the response and direct provider connection deterministically.

The header preflight is an optimization and an early rejection boundary, not proof that the eventual body is trustworthy or complete. A provider can omit or misstate its declared length, so every accepted response remains subject to the authoritative cumulative byte counter.

This boundary applies uniformly to chat responses, raw OpenAI-compatible passthrough, batch metadata, batch result downloads, and SSE streaming because those paths all consume the same response wrapper.

## Failure semantics

Oversize provider content and invalid or ambiguous framing are not retried as transient network errors. Retrying the same policy-invalid representation would amplify provider load, duplicate spend, and resource consumption without changing the violated contract.

Header-access failures become one stable redacted runtime error. Provider-controlled exception text is not exposed to callers or logs through this boundary. Cleanup is attempted immediately and cleanup failure cannot replace the original framing error.

The service does not publish partial JSON, partial batch evidence, or a partial streamed line after the byte budget is exceeded. Callers receive a failure and can split a legitimate large batch into smaller bounded requests.

## Verification contract

`tests/test_provider_response_bounds.py` preserves the test-first regression surface. It proves:

- the reviewed default is exactly 8 MiB;
- invalid byte budgets fail closed;
- over-budget declared lengths fail before a body read;
- equal repeated decimal lengths, including leading-zero equivalents, remain valid;
- malformed, non-ASCII, and conflicting declared lengths fail closed;
- `Content-Length` plus `Transfer-Encoding` fails as ambiguous;
- header lookup failures are redacted and close both resources;
- an unbounded read probes only one byte beyond the remaining budget;
- bodies exactly at the limit remain valid;
- repeated explicit reads cannot bypass cumulative accounting;
- negative full-read semantics remain bounded;
- HTTP/SSE iteration uses bounded `readline()` calls;
- cumulative streaming overflow fails; and
- response and connection cleanup still occurs when framing or consumption validation fails.

The test-only commits precede the production framing implementation in branch history. The focused deterministic tests require no provider credential or network egress. Repository and central exact-head gates remain separately authoritative.

## Operational and compatibility notes

The bound is intentionally enforced below model- or provider-specific parsing so malformed content cannot claim a larger allowance by choosing another response shape. No provider identity, model-routing policy, reviewer credential, or authority boundary changes.

A provider that sends both `Content-Length` and `Transfer-Encoding`, conflicting repeated lengths, or non-decimal length evidence is treated as incompatible. Operators should preserve the bounded failure, retain the provider and endpoint identity in redacted incident evidence, and correct or replace the upstream integration rather than adding a local parsing exception.

If production evidence shows a legitimate response class consistently approaching 8 MiB, raise a separately reviewed change with workload measurements and an explicit threat-model update. Do not disable the bound locally, truncate silently, or add an unreviewed environment-variable bypass.

## Rollback

If a compatibility regression is discovered, revert the framing-preflight and bounded-response commits as reviewed units and preserve the prior DNS-pinning, TLS identity, redirect, proxy-isolation, and cleanup controls. A rollback is not authorization to introduce an unbounded alternative transport or accept ambiguous HTTP framing.

## APA 7 references

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics* (RFC 9110; STD 97). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110.html

OWASP Foundation. (2023). *API4:2023 unrestricted resource consumption*. OWASP API Security Top 10. https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/

Python Software Foundation. (2026). *http.client — HTTP protocol client*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/http.client.html
