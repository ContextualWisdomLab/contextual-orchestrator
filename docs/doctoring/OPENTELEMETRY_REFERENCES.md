# OpenTelemetry references and implementation traceability

## Normative references

- OpenTelemetry Authors. (n.d.). *Manual instrumentation with OpenTelemetry
  Python*. Retrieved August 21, 2026, from
  https://opentelemetry.io/docs/languages/python/instrumentation/
- OpenTelemetry Authors. (n.d.). *Service semantic conventions*. Retrieved
  August 21, 2026, from
  https://opentelemetry.io/docs/specs/semconv/registry/attributes/service/
- ContextualWisdomLab governance-risk-compliance. (2026). *ADR 0009:
  Emit bounded OpenTelemetry request telemetry*. Retrieved August 21, 2026,
  from https://github.com/ContextualWisdomLab/governance-risk-compliance/blob/develop/docs/adr/0009-opentelemetry-request-telemetry.md

## Implementation mapping

| Concern | Implementation | Evidence boundary |
| --- | --- | --- |
| Service resource | `OTEL_SERVICE_NAME`, default `contextual-orchestrator` | One logical service name per deployment |
| Request correlation | `X-LineageWeave-Session-Id` and compatible metadata | Correlation only; not identity or authorization |
| Provider calls | `TaskOrchestrator` provider chat/embedding spans | Model capability and peer host; no prompt, answer, key, or response |
| Export | Bootstrap OTEL_EXPORTER_OTLP_ENDPOINT into the process KV | Disabled by default; runtime reads KV and sends to the normalized /v1/traces signal |

The GRC repository remains the organization control and evidence owner. The
gateway emits operational signals and does not copy GRC tables or provider
credentials.
