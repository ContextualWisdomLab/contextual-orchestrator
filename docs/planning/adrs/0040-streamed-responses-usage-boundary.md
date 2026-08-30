---
id: "0040"
title: "Record streamed Responses usage at the workflow boundary"
status: accepted
proposed_date: "2026-08-29"
accepted_date: "2026-08-29"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/cost_router.py"
  - "contextual_orchestrator/server.py"
related:
  - path: "docs/planning/adrs/0035-structured-provider-orchestration.md"
    relation: extends
success_criteria:
  - metric: "stream usage provenance"
    target: "provider-declared usage is retained per completed workflow trace step"
    source: "tests/test_true_streaming.py and tests/test_cost_router_boundaries.py"
  - metric: "missing usage honesty"
    target: "omitted provider usage is unavailable and never estimated from answer text"
    source: "tests/test_orchestrated_responses_stream.py"
---

# Record streamed Responses usage at the workflow boundary

## Context

The orchestrated `/v1/responses` stream previously emitted prompt-free
analytics but bypassed the cost coordinator. The provider stream parser also
discarded an optional terminal usage frame. Estimating a multi-agent bill from
the final synthesized answer would lose provider and step attribution and
would claim precision the provider did not report.

## Decision

The existing stdlib SSE parser records a provider-declared usage object on the
served trace step. An agent requests the internal
`stream_options.include_usage=true` option only when its explicit
`stream_usage_supported` capability is true; local gateway upstreams leave it
off because the public gateway stream-options contracts reject that flag. The
server gives a streamed route a workflow id, waits for
the existing workflow persistence boundary, and asks the cost coordinator to
record one ledger row per completed trace step with `request_channel=stream`.
Valid non-negative provider counts are `measured`. A missing or malformed
provider count is recorded with zero token fields and
`measurement_status=unavailable`; those zeroes are a storage sentinel, not a
free-cost assertion and not a text-derived estimate. Stable workflow-step
identities prevent duplicate rows if the boundary is replayed.

The final Responses object exposes standard usage fields only when all rows
are measured. Its gateway cost object retains `measurement_status`, and the
gateway usage-record identities remain available for reconciliation. A
disconnect or provider stream that ends before a terminal usage frame remains
unavailable.

## Consequences

- Multi-agent streamed usage is attributable to the exact provider/model trace
  step and workflow run.
- A buyer can distinguish measured spend from unavailable spend without seeing
  prompts, answers, or provider diagnostics.
- Providers that do not send usage still require a later provider-backed
  reconciliation path if exact billing is needed.
- True partial answer-token streaming and cancellable dependency scheduling are
  separate work; this decision does not infer usage from partial output.

## References

OpenAI. (n.d.). *Streaming events | OpenAI API reference*. Retrieved August 29,
2026, from https://platform.openai.com/docs/api-reference/responses-streaming

OpenTelemetry. (n.d.). *GenAI semantic conventions*. Retrieved August 29, 2026,
from https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
