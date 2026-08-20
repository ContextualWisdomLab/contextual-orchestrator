# ADR-0012: Optional sampling capability negotiation

- Status: Accepted
- Date: 2026-08-20
- Decision owners: contextual-orchestrator maintainers

## Context

Provider gateways may reject an optional sampling control such as `temperature`
for a selected deployment. The rejection is a provider capability response, not
evidence that another model should be selected. The previous implementation
only retried this case for `auto` Chat Completions requests with HTTP 400, which
left Responses, explicit Chat Completions, raw requests, and HTTP 422 failures
unhandled.

## Decision

When a provider returns a recognized capability error (HTTP 400 or 422) for a
request containing `temperature`, contextual-orchestrator retries exactly once
on the same provider and endpoint after omitting that optional field. This
negotiation applies equally to Chat Completions, Responses, and raw/proxy
requests.

The orchestrator must not infer capability from a model name, maintain a local
fallback model table, or silently choose a different model. `auto` reasoning
and model discovery remain orchestrator-owned according to ADR-0010 and
ADR-0011; this decision only removes an optional wire control that the selected
provider explicitly rejected.

## Consequences

- Models that only accept their default sampling behavior can still complete a
  request without an unrelated model fallback failure.
- The original request remains visible to the existing request lineage, while
  the effective retry omits only the rejected optional control.
- A non-capability error, a request without `temperature`, or a second failure
  is still raised unchanged.

## References

- ContextualWisdomLab. (2026). *ADR-0010: Gateway-only provider contract*.
- ContextualWisdomLab. (2026). *ADR-0011: Paper-grounded adaptive reasoning policy*.
