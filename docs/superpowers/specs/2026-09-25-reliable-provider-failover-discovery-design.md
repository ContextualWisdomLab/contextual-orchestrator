# Reliable Provider Failover and Catalog Discovery Design

## Goal

Make virtual review-pool routing exhaust every safe transient provider candidate
before failing, while repairing Experiential Labs credential compatibility and
making Bytez catalog refreshes tolerant of transient and provider-shaped
responses.

## Scope

This change covers the Python gateway's request-time candidate loop,
provider-credential bootstrap/discovery/admission identity, and mock HTTP
regressions. It does not change explicit concrete-model replay semantics, grant
Experiential Labs ZDR capability, or add a dependency. The Rust tree is not
modified unless repository inspection proves it is the active path for these
requests.

## Design

### Request-time fallback

Use the existing `TaskOrchestrator._invoke` and
`_invoke_with_rate_limit_recovery` boundary. A virtual selector advances to the
next eligible candidate for retryable provider failures, including HTTP 408,
425, 429, 500, 502, 503, 504 and connection/reset/timeout failures. The
candidate's circuit and rate-limit state are updated according to the existing
failure taxonomy:

- 429 is quota evidence and receives provider or bounded assumed cooldown
  handling without circuit-health attribution.
- 503 is availability evidence and advances immediately; a cooldown is honored
  only when the provider supplies one.
- Other retryable transport failures advance without replaying an explicit
  concrete-model request.
- Non-retryable authorization, malformed-request, content-policy, and similar
  failures preserve their existing failover/terminal policy.

The invocation loop accumulates one bounded attempt record per candidate. On
exhaustion, the final `ProviderUpstreamError` retains the tried count and
secret-free reason/status for every candidate. Existing passthrough attempt
evidence remains compatible.

### Credential identity

`EXPERIENTIAL_LABS_API_KEY` is canonical. `EXPERIENTAL_LABS_API_KEY` remains an
accepted input alias. Credential resolution canonicalizes both names before
bootstrap storage, discovery, free-pool admission, and provider/ZDR identity
comparisons. Internal discovered rows and persisted agent identity use the
canonical spelling. Experiential rows receive no implicit ZDR evidence.

### Experiential Labs discovery

Keep `GET https://api.experientiallabs.ai/v1/models` and Bearer authorization.
The official OpenAPI and provider source document confirm that the endpoint is
OpenAI-compatible but identity-only, so the parser must retain model IDs while
leaving unsupported pricing, capabilities, and privacy fields unknown. Tests
will verify request authorization, canonical credential identity, and
OpenAI-style model-list parsing without a real key.

### Bytez discovery

Keep the documented `GET https://api.bytez.com/models/v2/list/models` endpoint,
bare-token `Authorization`, and task-scoped requests. Try `chat`, then
`text-generation` only when the first catalog is empty or transiently
unavailable. Use the existing bounded retry/backoff contract for transient
HTTP/transport failures. Parse the documented `{error, output}` envelope and
support bounded page/cursor envelopes when present, while never broadening to an
unfiltered catalog. Empty or malformed catalogs fail closed with existing
provider error telemetry and no secret/body leakage.

## Verification

Tests will be written before implementation for:

1. mixed transient failover through all virtual candidates and final attempt
   evidence;
2. preservation of explicit concrete-model stickiness and non-retryable
   behavior;
3. both Experiential Labs environment/KV spellings and canonical discovery
   identity;
4. Bytez 500 retry/recovery, empty-chat task fallback, pagination, and
   fail-closed malformed/empty payloads.

Relevant focused tests, repository security metadata/action checks, and the
full Python test suite will be run before the final non-draft PR.

