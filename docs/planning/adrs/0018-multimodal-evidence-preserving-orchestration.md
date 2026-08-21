---
id: "0018"
title: "Preserve multimodal evidence through every evidence-bearing workflow step"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-20"
deciders:
  - "repository maintainer"
consulted:
  - "Sakana Fugu Technical Report"
  - "TRINITY: An Evolved LLM Coordinator"
  - "Learning to Orchestrate Agents in Natural Language with the Conductor"
  - "OpenAI Chat Completions and Responses API references"
informed:
  - "LineageWeave"
  - "OpenCode"
  - "Noema"
  - "Strix"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "tests/test_multimodal_workflow_evidence.py"
related:
  - path: "docs/planning/adrs/0013-paper-grounded-adaptive-reasoning-policy.md"
    relation: extends
effort: S
---

# Preserve multimodal evidence through every evidence-bearing workflow step

## Context

The OpenAI-compatible boundary accepts Chat Completions `image_url` parts and
Responses `input_image` parts, but the conducted workflow reduced the original
request to text before thinker, worker, verifier, and synthesizer execution.
The models therefore received the literal marker `[image]`, not the pixels.
An authorized, non-identifying LineageWeave runtime check exposed the product
impact: a completed five-image VISION run persisted five captions but zero OCR
characters. Transport completion was incorrectly stronger than evidence
completion.

Fugu, TRINITY, and Conductor support adaptive coordination across specialized
workers; they do not support removing the task evidence needed by those
workers. The official OpenAI API contracts represent image input as typed
content blocks, not as prose placeholders. The orchestrator must preserve
that typed evidence while retaining access-list isolation for prior model
outputs.

## Decision

- Normalize Responses `input_image` blocks to the existing Chat Completions
  `image_url` representation at the provider-neutral boundary.
- Retain the original validated image blocks beside each workflow step's text
  instruction. Access lists still govern prior model outputs; source evidence
  is part of the original task, not another agent's hidden state.
- Route image-bearing work and failover only through enabled agents that
  explicitly advertise the `vision` capability tag. Do not infer VISION
  support from a provider name or model identifier.
- Fail closed before provider I/O when no enabled VISION-capable worker is
  available. A text-only answer to an unseen image is not a valid fallback.
- Keep the public request shape and provider-neutral gateway boundary. This
  change adds no provider SDK, model-name ordering, or direct provider path.

## Consequences

- Thinker, worker, verifier, and synthesizer steps can independently inspect
  the same source pixels while seeing only the prior outputs allowed by the
  workflow access list.
- Chat Completions and Responses use one internal multimodal representation.
- Image bytes cross the same configured provider boundary more than once in a
  deep workflow. That is deliberate quality-oriented test-time compute, and
  the existing request-size and URL validation remain authoritative.
- A wrongly tagged pool fails visibly and requires an operator to correct its
  capability catalog instead of silently accepting fabricated visual work.

## Verification

A synthetic content-block regression must prove that every conducted step
receives the source image, text-only requests remain strings, Responses image
parts survive normalization, failover never enters a non-VISION agent, and a
pool without a VISION agent fails before any client call.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388). arXiv. https://doi.org/10.48550/arXiv.2512.04388

OpenAI. (n.d.-a). *Create chat completion*. OpenAI API reference. Retrieved
August 20, 2026, from
https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions

OpenAI. (n.d.-b). *Create a model response*. OpenAI API reference. Retrieved
August 20, 2026, from
https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H.,
Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., &
Clanuwat, T. (2026). *Sakana Fugu technical report* (arXiv:2606.21228).
arXiv. https://doi.org/10.48550/arXiv.2606.21228

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*TRINITY: An evolved LLM coordinator* (arXiv:2512.04695). arXiv.
https://doi.org/10.48550/arXiv.2512.04695
