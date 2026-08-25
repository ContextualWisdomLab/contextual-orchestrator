# OpenTelemetry references and implementation traceability

## Normative references

- OpenTelemetry Authors. (n.d.). *Manual instrumentation with OpenTelemetry
  Python*. Retrieved August 21, 2026, from
  https://opentelemetry.io/docs/languages/python/instrumentation/
- OpenTelemetry Authors. (n.d.). *Service semantic conventions*. Retrieved
  August 21, 2026, from
  https://opentelemetry.io/docs/specs/semconv/registry/attributes/service/
- OpenTelemetry Authors. (n.d.). *Semantic conventions for generative AI
  spans*. Retrieved August 21, 2026, from
  https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
- ContextualWisdomLab governance-risk-compliance. (2026). *ADR 0009:
  Emit bounded OpenTelemetry request telemetry*. Retrieved August 21, 2026,
  from https://github.com/ContextualWisdomLab/governance-risk-compliance/blob/develop/docs/adr/0009-opentelemetry-request-telemetry.md

## Implementation mapping

| Concern | Implementation | Evidence boundary |
| --- | --- | --- |
| Service resource | `OTEL_SERVICE_NAME`, default `contextual-orchestrator` | One logical service name per deployment |
| Request correlation | `X-LineageWeave-Session-Id`, compatible metadata, and W3C Trace Context | Correlation only; not identity or authorization; raw session identifiers never enter spans, logs, or OTLP exports; only the bounded hash is emitted; inbound baggage is not forwarded to providers |
| Provider calls | `ModelClient` chat/embedding CLIENT spans | Required GenAI operation/provider attributes, model and server destination; no prompt, answer, key, or response |
| Export | Bootstrap OTEL_EXPORTER_OTLP_ENDPOINT into the process KV | Disabled by default; runtime reads KV and sends to the normalized /v1/traces signal |

The GRC repository remains the organization control and evidence owner. The
gateway emits operational signals and does not copy GRC tables or provider
credentials.
