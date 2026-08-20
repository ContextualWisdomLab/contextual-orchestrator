# ADR 0012: Gateway-owned model selection and multi-agent structured output

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
- `--auto-discover-model-agents` expands an empty seed agent from its configured
  HTTPS `/models` endpoint. Embedding-only registry rows are excluded from the
  chat pool. Consumers provide only the gateway URL and credential.
- `json_object`, `json_schema`, and Responses text JSON formats force the
  conduct workflow. The final synthesis receives the output contract and the
  gateway validates the resulting JSON locally before returning it.
- Tool-loop requests are not proxied to one agent. Until a multi-agent tool
  execution contract exists, they return a named `422` rather than claiming an
  orchestrated result.

## Consequences

- Provider model selection remains centralized and can change with the registry
  without an application rebuild.
- Structured output retains the multi-agent trace and cannot bypass synthesis.
- Tool callers must wait for a future multi-agent tool protocol; no silent
  single-agent fallback is permitted.
