# ADR 0122: Correlate gateway provider telemetry by caller session

## Status

Accepted.

## Context

The gateway can route one request through several workers and providers. A
caller-provided post session already exists in compatible metadata, but it was
not bound to the HTTP request or provider diagnostics. The organization GRC
service owns the low-cardinality, secret-free telemetry control in its ADR
0009; this service must emit evidence that can be consumed there without
becoming a second GRC store.

## Decision

Telemetry deployment settings may enter the process KV during bootstrap from non-secret OTEL_* transport settings; runtime telemetry reads the injected KV only. A configured OTLP base URL is normalized to the HTTP /v1/traces signal endpoint.

1. Use the OpenTelemetry Python API, SDK, and OTLP HTTP exporter. Export is
   disabled unless `OTEL_EXPORTER_OTLP_ENDPOINT` is explicitly configured.
2. Accept `X-LineageWeave-Session-Id` and compatible metadata fields, bind the
   normalized value to the request context, and reset it when the request
   handler finishes. Extract and inject only W3C `traceparent`/`tracestate`;
   caller-controlled baggage never crosses the provider egress boundary. Raw
   session identifiers never enter telemetry attributes, spans, logs, or OTLP
   exports; only the bounded correlation hash may be emitted.
3. Add the bounded session correlation to provider spans for chat and embedding
   calls. Follow the current OpenTelemetry GenAI span convention: emit CLIENT
   spans named `chat {model}` or `embeddings {model}`, include the required
   `gen_ai.operation.name` and `gen_ai.provider.name` attributes, and use
   `server.address` / `server.port` for the transport destination. Record
   `error.type` on failure, but never prompt, answer, request body, API key, or
   raw provider response.
4. Keep structured-output, Responses API, VISION, embedding, and multi-agent
   requests on the same orchestration path. Telemetry observes that path; it
   does not introduce a single-agent fallback or a second credential source.

## Consequences

An operator can follow one LineageWeave post through gateway routing and
provider failures while GRC receives aggregate operational evidence rather
than copied product data. Session correlation is diagnostic only: it is not an
identity, tenant, authorization, or evidence label.

## References

OpenTelemetry Authors. (n.d.). *Manual instrumentation with OpenTelemetry
Python*. Retrieved August 21, 2026, from
https://opentelemetry.io/docs/languages/python/instrumentation/

OpenTelemetry Authors. (n.d.). *Service semantic conventions*. Retrieved
August 21, 2026, from https://opentelemetry.io/docs/specs/semconv/registry/attributes/service/

OpenTelemetry Authors. (n.d.). *Semantic conventions for generative AI spans*.
Retrieved August 21, 2026, from
https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
