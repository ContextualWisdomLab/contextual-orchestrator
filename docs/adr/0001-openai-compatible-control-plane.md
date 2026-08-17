# ADR 0001: OpenAI-compatible control plane

- Status: Accepted
- Date: 2026-08-16

## Context

Callers already speak OpenAI-style chat completions. Enterprise operators still
need a hidden pool, routing, verification, and audit. Shipping a new RPC or a
vendor-specific SDK would force every consumer (including gyeot and scopeweave)
to migrate.

[docs/rest_api_design.md](../rest_api_design.md) keeps the compatibility
endpoint at `/v1/chat/completions` and publishes the handwritten contract at
`GET /openapi.json`. [docs/library_research.md](../library_research.md) names
OpenAPI 3.1 as the contract format for review and client generation.

## Decision

Expose **one public inference interface**: `POST /v1/chat/completions`.
Orchestration mode, agent selection, access lists, and traces stay behind that
front door. Operator resources use the `/api/v1` prefix and two-or-more-word
snake_case names. The machine-readable contract is OpenAPI 3.1
(`GET /openapi.json`).

`"stream": true` returns an OpenAI-compatible `text/event-stream` of
`chat.completion.chunk` events terminated by the SSE sentinel `data: [DONE]`.
That sentinel is Server-Sent Events framing, not a `data:` URL scheme.

## Consequences

- Existing OpenAI-compatible clients can adopt the gateway without a new SDK.
- Full orchestration traces are opt-in for trusted callers; they are not the
  default public response shape.
- A second public chat protocol is out of scope until a second real consumer
  cannot use `/v1/chat/completions`.

## References

OpenAPI Initiative. (2024). *OpenAPI Specification v3.1*. https://spec.openapis.org/oas/v3.1.0.html
