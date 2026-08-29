---
title: "Streamed Responses usage and cost evidence"
status: "implemented on feature branch"
date: "2026-08-29"
scope: "ADR 0038"
---

# Streamed Responses usage and cost evidence

## Contract

OpenAI's streaming reference defines `response.created` as an in-progress
response and `response.completed` as the terminal response. The terminal
response usage object uses `input_tokens`, `output_tokens`, and `total_tokens`.
OpenAI's Chat Completions reference also warns that an interrupted stream may
not receive its final usage chunk. The gateway therefore treats missing usage
as an evidence state, not as a zero-cost response.

The implementation keeps provider usage on each completed workflow trace step,
records it through the existing cost ledger, and returns standard Responses
usage only when all steps have measured counts. Any missing step yields
`measurement_status=unavailable`, `usage=null`, and `cost.cost_amount=null` in
the completed gateway response. No prompt or answer text is copied into the
ledger for this decision.

## Observability mapping

OpenTelemetry's current GenAI semantic conventions use
`gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`, and identify the
provider and model separately. The cost ledger follows that separation:
execution provider/model come from the served trace, while account/team/
service attribution remains descriptive caller metadata. The request channel
`stream` distinguishes these rows from synchronous and batch accounting.

## Acceptance checks

- Provider SSE usage-only frames survive parsing and are available through
  `ModelClient.take_usage()`.
- Multiple completed trace steps produce multiple measured stream ledger rows
  and one aggregate Responses usage object.
- Mock/unreported usage produces unavailable rows and no answer-text estimate.
- A disconnected Responses stream does not start later orchestration work and
  still releases its execution slot.

## References

OpenAI. (n.d.). *Chat completions API reference*. Retrieved August 29, 2026,
from https://platform.openai.com/docs/api-reference/chat/create

OpenAI. (n.d.). *Streaming events | OpenAI API reference*. Retrieved August 29,
2026, from https://platform.openai.com/docs/api-reference/responses-streaming

OpenTelemetry. (n.d.). *GenAI semantic conventions*. Retrieved August 29, 2026,
from https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
