---
id: "0011"
title: "Paper-grounded adaptive reasoning and model capability policy"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-20"
deciders:
  - "repository maintainer"
consulted:
  - "Route to Reason: Adaptive Routing for LLM and Reasoning Strategy Selection"
  - "Route-and-Reason: Scaling Large Language Model Reasoning with Reinforced Model Router"
  - "Reasoning on a Budget: A Survey of Adaptive and Controllable Test-Time Compute in LLMs"
  - "Ares: Adaptive Reasoning Effort Selection for Efficient LLM Agents"
informed:
  - "LineageWeave"
  - "fast-mlsirm"
  - "contributors"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/model_discovery.py"
  - "tests/test_openai_passthrough.py"
  - "tests/test_request_metadata.py"
  - "docs/architecture.md"
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0010-gateway-only-provider-contract.md"
    relation: extends
effort: M
---

# Paper-grounded adaptive reasoning and model capability policy

## Context

The public API may receive a requested reasoning level such as `auto`,
`medium`, `high`, or `xhigh`, while the selected provider may support a
different subset of values or no reasoning control at all. A fixed value is
also a poor policy for multi-step work: easy steps can be over-computed and
hard steps can be under-computed. The repository must therefore distinguish
the caller's policy from the provider wire value and must not make model
decisions from model-name folklore.

## Decision

- Model selection, reasoning-effort allocation, orchestration topology, and
  quality/cost claims are decided from cited academic papers plus current
  runtime capability and measurement evidence. Vendor documentation defines
  wire compatibility; it does not define this repository's model policy.
- `auto` is an orchestrator-only policy. The orchestrator evaluates task/step
  difficulty, capability advertisements, budget, latency constraints, and
  required verification, then chooses a provider-supported effort or a
  multi-agent workflow. The literal value `auto` is never sent upstream.
- Explicit effort values are forwarded only when the selected provider
  advertises them. `none` is not a universal synonym for a non-reasoning
  model; if the provider does not advertise a requested value, the
  orchestrator negotiates another supported path or fails clearly.
- `high` and `xhigh` are outcome policies, not promises that one worker has a
  particular hidden-thinking implementation. When appropriate, the
  orchestrator may use heterogeneous workers, independent attempts,
  verification, and synthesis. Traces must record the effective strategy and
  must not label a non-reasoning worker as a reasoning model.
- No direct MLX transport or MLX-specific model policy is permitted. Local
  runtimes remain behind the authenticated provider-neutral gateway boundary
  in ADR 0010.

## Evidence contract

Every change to routing or reasoning policy must cite the relevant sources in
`docs/papers/README.md`, add or update a regression test for the capability
boundary, and report requested versus effective effort in the trace or
metadata. A provider health result alone is not evidence of reasoning quality.

Transport compatibility is checked against the current provider API contract,
not treated as model-policy evidence. In particular, Responses API capability
checks may cover supported reasoning-effort values and `json_schema` structured
outputs; Chat Completions compatibility must negotiate its system-message and
structured-output equivalent separately. These checks must never turn a vendor
default into this repository's reasoning policy.

## Consequences

- Callers can request `auto` without coupling themselves to provider-specific
  effort names.
- Unsupported effort values cannot leak to providers or silently become a
  different model behavior.
- Adaptive multi-agent execution is measurable as orchestration, rather than
  being misrepresented as a provider's native reasoning capability.
- Historical MLX benchmark and transport ADRs remain available as provenance,
  but they are not supported configuration guidance.
