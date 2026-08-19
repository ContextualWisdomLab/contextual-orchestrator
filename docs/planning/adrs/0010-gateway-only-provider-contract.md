---
id: "0010"
title: "Gateway-only provider contract; no direct MLX transport"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-20"
deciders:
  - "repository maintainer"
consulted:
  - "contextual-orchestrator provider capability contract"
  - "paper-grounded model routing policy"
informed:
  - "LineageWeave"
  - "fast-mlsirm"
  - "contributors"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/model_discovery.py"
  - "contextual_orchestrator/__main__.py"
  - "examples/agents.local.json"
  - "docs/kv-credentials.md"
supersedes: "0002-explicit-local-mlx-evaluation"
superseded-by: null
effort: M
---

# Gateway-only provider contract; no direct MLX transport

## Context

The orchestrator is the model routing and orchestration boundary. A direct
runtime-specific `mlx://` worker contract leaks one local inference runtime
into the public agent schema, CLI, credential rules, and Responses-to-Chat
adaptation. It also creates provider-specific controls that cannot be applied
to other models or gateways.

## Decision

- The public worker contract is provider-neutral: `mock://` for tests,
  `https://` for remote providers, and authenticated `local://` only for a
  reviewed loopback gateway.
- Direct `mlx://` agents are rejected at `ModelAgent` construction. No MLX
  runtime, model-template setting, or keyless direct transport is part of the
  orchestrator contract.
- A local gateway owns downstream model selection and runtime-specific
  settings. The orchestrator sends only the negotiated provider-neutral
  request shape and the explicitly named local gateway credential.
- Model selection and reasoning policy remain capability- and paper-driven;
  they must not infer a provider from a model name or hard-code MLX behavior.

## Consequences

- LineageWeave and other callers can use one gateway boundary without a direct
  local-model dependency or monkey patch.
- Existing local gateway concurrency and Responses/Chat compatibility remain
  available because they are transport capabilities, not MLX behavior.
- Historical MLX benchmark artifacts remain for provenance but are not current
  configuration guidance or a supported public transport.
- Operators who previously configured `mlx://` must place the runtime behind
  an authenticated OpenAI-compatible gateway and configure `local://` or
  `https://` accordingly.
