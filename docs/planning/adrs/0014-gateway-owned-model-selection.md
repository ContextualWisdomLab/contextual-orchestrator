---
id: "0014"
title: "Gateway-owned model selection and multi-agent structured output"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-20"
deciders:
  - "repository maintainer"
consulted:
  - "gateway-only provider contract"
  - "paper-grounded adaptive reasoning policy"
informed:
  - "LineageWeave"
  - "fast-mlsirm"
  - "contributors"
affected_components:
  - "contextual_orchestrator/__main__.py"
  - "contextual_orchestrator/cost_router.py"
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0012-gateway-only-provider-contract.md"
    relation: depends-on
  - path: "docs/planning/adrs/0013-paper-grounded-adaptive-reasoning-policy.md"
    relation: implements
effort: M
---

# ADR 0014: Gateway-owned model selection and multi-agent structured output

- Status: Accepted
- Date: 2026-08-20

## Context

Consumers using contextual-orchestrator must not select a provider model by
copying `LLM_GATEWAY_MODEL` into every application. The configured gateway
exposes its model registry, and the orchestrator owns routing, reasoning effort,
and cost attribution. A request carrying JSON output constraints or the
Responses API must not silently downgrade to a single provider call merely
because the provider response shape is richer.

## Decision

- An omitted chat or Responses `model` is represented by the virtual
  `contextual-orchestrator` model and is resolved inside the orchestrator.
- `reasoning_effort=auto` (or Responses `reasoning.effort=auto`) is an
  orchestrator-only policy value and is never forwarded as a provider field.
  Provider-native levels are forwarded only after the selected agent declares
  that capability; support is never inferred from a model name. If no selected
  provider declares the requested level, the gateway rejects the request rather
  than silently falling back to a different effort.
- `--auto-discover-model-agents` expands an empty seed agent from its configured
  HTTPS `/models` endpoint. Embedding-only registry rows are excluded from the
  chat pool. Consumers provide only the gateway URL and credential.
- `json_object`, `json_schema`, and Responses text JSON formats force the
  conduct workflow. The final synthesis receives the original provider-native
  output contract, and the gateway independently validates the resulting JSON
  locally before returning it. A Chat request therefore keeps
  `response_format`, while a Responses request keeps `text.format`, at the
  final provider boundary.
- Tool-loop requests are explicitly passed to one selected worker agent. The
  gateway preserves the provider's full tool-call response and the client owns
  execution of the returned function calls; they do not claim a multi-agent
  synthesis trace. Streaming tool loops are rejected until the gateway has a
  provider-shape-preserving streaming relay. Clients must opt in with the
  `X-Contextual-Orchestrator-Tool-Loop: v1` header; ordinary tool requests stay
  fail-closed until that contract is explicitly selected.
- Each provider-reported call in a conducted workflow writes its own cost-ledger
  record under the shared workflow run id, including the model judge and final
  provider synthesis. The response retains one last-metered-call
  `usage_record_id` for compatibility and adds the complete `usage_record_ids`
  list. Calls without
  valid provider usage increment `unmetered_provider_call_count`; if no workflow
  call reports usage, the existing request-level estimate remains the explicit
  compatibility fallback.

## Consequences

- Provider model selection remains centralized and can change with the registry
  without an application rebuild.
- Structured output retains the multi-agent trace and cannot bypass synthesis.
- Cost reports price each metered workflow call against the model that served it
  instead of attributing all conducted work to the final synthesizer.
- A response never sums monetary amounts across currencies; mixed-currency
  workflows expose `currency_code=MIXED` and a null aggregate amount while the
  individual ledger records retain their original amounts and currencies.
- Tool callers use an explicit single-agent passthrough contract. The gateway
  remains the model-selection boundary, while tool execution stays with the
  authenticated client and never becomes an implicit multi-agent fallback.
