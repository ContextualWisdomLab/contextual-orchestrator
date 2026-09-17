---
id: "0132"
title: "Remove the unsourced shared generation-token ceiling"
status: accepted
proposed_date: "2026-09-17"
accepted_date: "2026-09-17"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/server.py"
related:
  - path: "docs/planning/adrs/0040-streamed-responses-usage-boundary.md"
    relation: related
success_criteria:
  - metric: "no shared ingress ceiling"
    target: "Chat, Completions, and Responses accept positive generation budgets without a gateway-wide numeric hard cap"
    source: "tests/test_generation_token_ingress.py"
  - metric: "Responses alias honesty"
    target: "Responses normalizes max_output_tokens over max_completion_tokens over max_tokens and forwards the canonical field"
    source: "tests/test_generation_token_ingress.py"
  - metric: "model-specific limits remain"
    target: "provider-published agent.max_output_tokens and client effective caps still bound generation"
    source: "existing model-budget and client-boundary tests"
---

# Remove the unsourced shared generation-token ceiling

## Context

Ingress validators for Completions `max_tokens`, Chat
`max_completion_tokens`, and Responses `max_output_tokens` rejected any
positive budget above `1_048_576`. That number entered the tree as a
"practical gateway hard ceiling" without a cited provider catalog limit,
operator policy, or verified product requirement (issue #1151). HTTP tests
proved rejection, not provenance. Numerical execution limits in this gateway
must derive from a provider/model constraint, an approved operator policy, or
a verified product requirement.

Separately, Responses accepted the legacy aliases but did not always keep a
canonical `max_output_tokens` value on the body used for provider forwarding,
so caller budgets could disappear after validation.

## Decision

Remove the shared `1_048_576` ingress ceiling. Keep positive-integer (and
coercion) validation. Keep model-specific and client `effective_max_output_tokens`
enforcement. Do not replace the removed number with another arbitrary
gateway-wide constant, and do not silently clamp.

On `/v1/responses`, normalize generation budgets with precedence
`max_output_tokens` > `max_completion_tokens` > `max_tokens` (falling through
nulls) onto `max_output_tokens` before provider forwarding.

## Consequences

- Callers may request generation budgets larger than the former shared ceiling;
  providers and model metadata still reject or bound physically unsupported
  sizes.
- Operators who need a gateway-wide cap must introduce an explicit, sourced
  policy (KV/operator config or catalog-derived limit), not an unsourced
  constant in the validator.
- Regression coverage uses a boundary fixture above the former cap only to
  prove passthrough; it does not claim any live model supports that size.

## References

OpenAI. (n.d.). *Create a model response | OpenAI API reference*
(`max_output_tokens`). Retrieved September 17, 2026, from
https://platform.openai.com/docs/api-reference/responses/create

OpenAI. (n.d.). *Chat Completions | OpenAI API reference*
(`max_completion_tokens`, `max_tokens`). Retrieved September 17, 2026, from
https://platform.openai.com/docs/api-reference/chat/create

Issue #1151 — Validate or replace the unsubstantiated common generation-token
ceiling.
