# ADR 0012: Optional sampling capability negotiation

- Status: Accepted
- Date: 2026-08-20

## Context

Some provider deployments reject the optional `temperature` request field even
when the value is valid for the public API contract. A provider response that
only reports an invalid value must not be silently changed into a different
request. The same transport boundary serves chat completions and raw Responses
passthrough, so the behavior must be endpoint-local and provider-neutral.

## Decision

When a provider returns HTTP 400 or 422 and the response evidence explicitly
identifies `temperature` as unsupported, the orchestrator retries once against
the same endpoint with only `temperature` removed. This negotiation is
available to both the normal chat transport and raw/Responses passthrough.

All other 4xx responses, including invalid temperature values, remain
non-retryable. The orchestrator does not infer capability from a model name,
provider ordering, parameter count, or local benchmark, and it does not select
another model as a temperature fallback.

## Consequences

- GPT-5-family or otherwise restricted deployments can answer when the only
  incompatibility is an optional sampling field.
- The original endpoint, model, authentication, and all other request fields
  remain unchanged.
- The provider error body is consumed only for bounded capability
  classification; it is not persisted or exposed as a credential-bearing log.

## Verification

`tests/test_provider_integration.py` covers successful chat negotiation,
invalid-value non-negotiation, and raw Responses negotiation over a real local
HTTP server.
