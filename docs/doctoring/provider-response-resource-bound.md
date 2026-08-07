# Provider response resource-bound evidence

## Decision record

Contextual Orchestrator treats every model-provider response body as untrusted input. The DNS-pinned transport therefore limits cumulative consumed response bytes to **8 MiB (8,388,608 bytes) per HTTP response** before JSON parsing, batch-output decoding, or server-sent-event processing can continue.

The 8 MiB value is a reviewed product safety bound, not a value mandated by HTTP, OWASP, or Python. It is intentionally high relative to ordinary chat/completion responses while remaining low enough to prevent one provider response from becoming an unbounded memory-consumption surface. Workloads whose legitimate batch output exceeds the bound must be partitioned into smaller batches rather than silently truncating evidence.

## Security and reliability basis

OWASP API4:2023 identifies missing or inappropriate resource limits as a common API weakness with denial-of-service and cost consequences, and recommends explicit bounds on data size and resource consumption. This applies to outbound provider integration as well as inbound APIs because a compromised, malfunctioning, or policy-incompatible upstream can return unexpectedly large data.

RFC 9110 defines the semantics of HTTP response content but does not impose an application-specific maximum representation size. The application therefore owns the responsibility to select and enforce a defensible consumption policy.

Python's `http.client.HTTPResponse.read([amt])` supports reading at most the next requested number of bytes. Contextual Orchestrator uses that primitive to request no more than the remaining response budget plus one byte. The single probe byte distinguishes an exact-limit response from an oversized response without first buffering the complete body.

## Runtime contract

`contextual_orchestrator.provider_transport._ProviderHTTPResponse` owns the bound for every existing `ModelClient` provider path. No caller-specific opt-in is required.

The contract is:

1. ordinary `read()` calls request at most the remaining budget plus one byte;
2. explicit smaller reads preserve the caller's requested size;
3. explicit negative or over-budget reads are reduced to the remaining budget plus one byte;
4. cumulative reads share one budget for the lifetime of the response wrapper;
5. real `http.client.HTTPResponse` iteration uses size-limited `readline()` calls so a single pathological SSE line cannot bypass the bound before inspection;
6. lightweight non-HTTP test doubles retain ordinary iteration while receiving the same cumulative accounting;
7. exceeding 8 MiB raises a non-transient runtime failure rather than returning truncated content; and
8. context-managed failure still closes both the response and the direct provider connection deterministically.

This boundary applies uniformly to chat responses, raw OpenAI-compatible passthrough, batch metadata, batch result downloads, and SSE streaming because those paths all consume the same response wrapper.

## Failure semantics

Oversize provider content is not retried as a transient network error. Retrying the same oversized representation would amplify provider load, duplicate spend, and resource consumption without changing the violated contract.

The service does not publish partial JSON, partial batch evidence, or a partial streamed line after the byte budget is exceeded. Callers receive a failure and can split a legitimate large batch into smaller bounded requests.

## Verification contract

`tests/test_provider_response_bounds.py` preserves the test-first regression surface. It proves:

- the reviewed default is exactly 8 MiB;
- invalid byte budgets fail closed;
- an unbounded read probes only one byte beyond the remaining budget;
- bodies exactly at the limit remain valid;
- repeated explicit reads cannot bypass cumulative accounting;
- negative full-read semantics remain bounded;
- HTTP/SSE iteration uses bounded `readline()` calls;
- cumulative streaming overflow fails; and
- response and connection cleanup still occurs when the limit is exceeded.

The tests are deterministic and require no provider credential or network egress.

## Operational and compatibility notes

The bound is intentionally enforced below model- or provider-specific parsing so malformed content cannot claim a larger allowance by choosing another response shape. No provider identity, model-routing policy, reviewer credential, or authority boundary changes.

If production evidence shows a legitimate response class consistently approaching 8 MiB, raise a separately reviewed change with workload measurements and an explicit threat-model update. Do not disable the bound locally, truncate silently, or add an unreviewed environment-variable bypass.

## Rollback

If a compatibility regression is discovered, revert the bounded-response commit as one reviewed unit and preserve the prior DNS-pinning, TLS identity, redirect, proxy-isolation, and cleanup controls. A rollback is not authorization to introduce an unbounded alternative transport.

## APA 7 references

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics* (RFC 9110; STD 97). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110.html

OWASP Foundation. (2023). *API4:2023 unrestricted resource consumption*. OWASP API Security Top 10. https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/

Python Software Foundation. (2026). *http.client — HTTP protocol client*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/http.client.html
