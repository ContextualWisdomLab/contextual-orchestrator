---
id: "0024"
title: "Orchestrator-owned automatic embedding model selection"
status: accepted
proposed_date: "2026-08-20"
deciders:
  - "repository maintainer"
consulted:
  - "contextual-orchestrator gateway runtime"
  - "downstream embedding consumers"
informed:
  - "downstream consumers (naruon, LineageWeave)"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/api_contract.py"
  - "contextual_orchestrator/batch_routing.py"
  - "tests/test_embeddings_model_pool_http_honesty.py"
effort: S
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: constrains
  - path: "docs/planning/adrs/0002-explicit-local-mlx-evaluation.md"
    relation: follows
---

# Orchestrator-owned automatic embedding model selection

## Context

Consumers currently have to send a model name to the embeddings endpoints. A
consumer that already delegates model selection to contextual-orchestrator
must then invent a sentinel model name or maintain provider-specific
configuration. That contradicts the gateway-owned model policy and makes the
OpenAI-compatible contract less useful for downstream services.

Embedding agents are already represented in the orchestrator candidate pool by
the explicit `embedding` capability tag. The selection must therefore reuse
the existing ranked-agent policy rather than add a provider order, model-name
guess, or consumer-side fallback.

## Decision

1. `/v1/embeddings` and `/v1/batch/embeddings` accept an omitted `model`.
2. When omitted, the gateway selects the highest-ranked enabled agent carrying
   the `embedding` capability. Ranking continues to use the existing priority
   and capability policy; disabled agents and provider exclusions are ignored.
   Discovery may attach that capability only from explicit provider or operator
   metadata; model-name guessing is not evidence of embedding support.
   Startup discovery applies the same rule to chat: a provider source may declare
   `chat` only when its listing endpoint is explicitly limited to chat/text LLMs.
   Unclassified sources and non-chat deployments remain disabled, and an empty
   eligible discovery result leaves the configured pool unchanged.
3. An explicitly supplied model remains supported only when it matches an
   enabled embedding-capable agent. Unknown, disabled, or non-embedding models
   fail closed with the existing invalid-model contract.
4. If no enabled embedding-capable agent exists for an omitted model, the
   gateway returns `503 embedding_unavailable`; it never invents a model or
   produces a heuristic vector as a provider substitute.
5. The resolved model is carried into internal batch requests, provider JSONL,
   pending and completed response metadata, and cost attribution so the selected
   deployment remains deterministic and auditable. The standalone in-process backend remains a
   local test/development path. When the active pool contains a remote
   embedding-capable agent, the default coordinator calls that agent's
   OpenAI-compatible `/embeddings` endpoint and records the provider-reported
   token count. It never substitutes the standalone SHA-256 vector for a
   configured remote agent.

## Contract and acceptance evidence

The OpenAPI contract marks `model` optional and documents the unavailable
response. Loopback HTTP tests cover omitted-model selection for sync and batch
requests, explicit pool validation, and the no-capability failure. Provider
backend contract tests preserve the resolved model in every serialized
embedding request. Discovery tests preserve explicit capability metadata into
the runtime agent pool and leave unclassified models ineligible.

## Consequences

LineageWeave, naruon, and other consumers can omit provider model selectors
while retaining pool validation, provider routing, and cost attribution.
Explicit OpenAI-compatible model requests are capability-gated, not backward
compatible: a named model must belong to the enabled agent pool **and** carry
the requested capability tag (for example ``embedding``), otherwise the
gateway returns ``400 invalid_model``. Operators migrating from earlier
builds must re-tag pool agents before clients that address embedding models
explicitly will resolve; omitted-model requests are unaffected because they
auto-select through the same capability gate. The gateway still exposes a
clear distinction between local standalone evidence and configured-provider
evidence; local heuristic vectors are not production provider evidence.

## Research grounding

The selection is a capability-constrained routing decision, not a semantic
quality judgment. It reuses the repository's vendored routing literature:

* Chen, L., Zaharia, M., & Zou, J. (2023). FrugalGPT: How to use large
  language models while reducing cost and improving performance. *arXiv*.
  https://arxiv.org/abs/2305.05176
* Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
  Kadous, M. W., & Stoica, I. (2024). RouteLLM: Learning to route LLMs with
  preference data. *arXiv*. https://arxiv.org/abs/2406.18665
* Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
  Lakshmanan, L. V. S., & Awadallah, A. H. (2024). Hybrid LLM:
  Cost-efficient and quality-aware query routing. *International Conference
  on Learning Representations*. https://arxiv.org/abs/2404.14618

These papers ground cost-aware and capability-aware routing decisions; they do
not provide evidence that one embedding model is universally higher quality.
No such unsupported quality claim is made by this ADR.

## More information

* docs/papers/README.md
* docs/rest_api_design.md
* docs/planning/adrs/0001-fail-closed-model-judgment.md
