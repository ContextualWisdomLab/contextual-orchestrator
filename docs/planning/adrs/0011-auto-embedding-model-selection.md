# ADR 0011: Orchestrator-owned automatic embedding model selection

- Status: Accepted
- Date: 2026-08-20
- Figma: N/A; this is an API and routing contract with no buyer-facing UI.

## Context

Consumers currently have to send a model name to the embeddings endpoints. A
consumer that already delegates model selection to contextual-orchestrator
must then invent a sentinel model name or maintain a provider-specific
configuration, which contradicts the gateway-owned model policy. Embedding
agents are already represented in the orchestrator candidate pool through the
`embedding` capability tag.

## Decision

1. `/v1/embeddings` and `/v1/batch/embeddings` accept an omitted `model`.
2. When omitted, contextual-orchestrator selects an enabled candidate carrying
   the `embedding` capability through its existing ranked-agent policy. The
   provider model name is resolved internally and is returned in the response
   metadata; consumers do not choose it.
3. An explicitly supplied model remains supported and must match an enabled
   embedding-capable agent. Unknown or disabled explicit models remain a
   client error.
4. No sentinel model name, provider ordering, model-name guess, or local
   embedding substitute is used on a configured provider path. If no enabled
   embedding agent exists, the gateway returns a clear unavailable response.
5. Internal batch requests carry the resolved model after selection so provider
   transports and cost attribution remain deterministic and auditable.

## Consequences

LineageWeave and other consumers can omit model selectors while retaining
provider-pool validation and cost attribution. Explicit OpenAI-compatible model
requests remain backward compatible. The no-capability case fails closed
instead of silently producing a heuristic vector.

## References

- Contextual-orchestrator model policy and auto-discovery implementation.
- Fugu, Conductor, and TRINITY literature register; model selection remains an
  orchestrator policy and is not reimplemented by a consumer.
