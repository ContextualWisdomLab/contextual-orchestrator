---
id: "0011"
title: "Keep structured provider features inside multi-agent orchestration"
status: accepted
proposed_date: "2026-08-21"
accepted_date: "2026-08-21"
deciders:
  - "repository maintainer"
consulted:
  - "LineageWeave integration"
  - "contextual-orchestrator runtime"
informed:
  - "API consumers"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "tests/test_openai_passthrough.py"
  - "tests/test_model_judge.py"
effort: M
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: constrains
  - path: "docs/planning/adrs/0002-explicit-local-mlx-evaluation.md"
    relation: extends
  - path: "docs/architecture.md"
    relation: implements
  - path: "docs/planning/adrs/0014-gateway-owned-model-selection.md"
    relation: constrained-by
success_criteria:
  - metric: "structured requests using the multi-agent workflow"
    target: "100% of client-facing non-null response_format and Responses requests"
    measurement_window: "every structured-output regression run"
    source: "tests/test_openai_passthrough.py"
  - metric: "Responses json_schema translation"
    target: "Responses text.format json_schema reaches the final provider as the equivalent Chat response_format without losing the schema"
    measurement_window: "every Responses structured-output regression run"
    source: "tests/test_openai_passthrough.py"
  - metric: "multimodal context preservation"
    target: "image_url input remains available to the final synthesis request"
    measurement_window: "every multimodal structured-output regression run"
    source: "tests/test_openai_passthrough.py"
---

# Keep structured provider features inside multi-agent orchestration

## Context

The OpenAI-compatible boundary previously treated `response_format` and the
Responses API as a provider passthrough. That made a request look
successful while skipping the Thinker/Worker/Verifier/Synthesizer workflow.
Structured output and multimodal requests are still product work, not an
exception to the orchestration contract. A consumer must receive the same
workflow evidence, verification boundary, session lineage, and cost accounting
as a plain chat request.

## Decision

1. A non-null structured-output contract or Responses request is an
   orchestration trigger, never a silent single-agent downgrade.
2. The request enters the existing conducted workflow. Intermediate steps use
   the original messages, including multimodal content, and the final
   synthesizer performs the provider-facing structured completion.
3. The final provider payload preserves validated tools and structured-output
   fields. A Responses request remains a Responses request at the final
   provider boundary when the selected provider supports it; a local provider
   may perform an explicit transport-level translation when its capability
   boundary requires Chat Completions. Responses `text.format` therefore stays
   native for Responses-capable providers rather than being silently downgraded.
4. `json_object` and `json_schema` are both first-class structured workflows.
   Schema validation remains fail-closed at the HTTP boundary; a provider
   success is not treated as semantic schema validity.
5. The workflow response exposes bounded orchestration metadata by default.
   Prompts, answers, images, tool arguments, secrets, and unbounded raw traces
   are not put into telemetry or the default response.
6. Tool execution loops are not fabricated by this decision. Per ADR 0014,
   clients must opt into the explicit client-owned `v1` tool-loop contract;
   ordinary tool declarations fail closed, while the opted-in provider-shape
   call remains a single-worker exception.
7. The internal fail-closed LLM-as-a-Judge call remains one bounded,
   schema-constrained provider request. It uses the orchestrator's existing
   provider transport but never recursively starts another conducted workflow.

## Research basis

This decision applies the existing research-grounded architecture rather than
inventing a provider-specific exception:

- Fugu distinguishes a low-latency routed call from a quality-oriented deep
  workflow and keeps the worker pool configurable.
- TRINITY supplies the Thinker, Worker, and Verifier role boundary used before
  synthesis.
- Conductor supplies explicit workflow steps and access-controlled context.

The canonical references are maintained in `docs/architecture.md` and
`docs/papers/README.md`. OpenAI's Chat Completions and Responses API contracts
define the wire-shape translation, not the orchestration policy.

## Consequences

* Good: structured and multimodal requests no longer bypass verification and
  orchestration evidence.
* Good: JSON object and JSON schema requests share one tested policy instead of
  diverging into transport-specific single-agent paths.
* Good: Responses-only providers receive their native endpoint and input shape
  after the multi-agent workflow.
* Good: the final provider retains the capability fields it must interpret.
* Good: internal verification does not recursively multiply provider calls or
  replace the judge verdict with an unrelated synthesized answer.
* Bad: structured requests consume more provider calls and can take longer than
  a plain routed request.
* Bad: tool execution remains a distinct explicit client-owned contract rather
  than being implied by merely forwarding a tool declaration.

## Confirmation

Run the focused structured-output and orchestration tests. Confirm that the
Responses JSON-schema test preserves the schema, the structured-output test
reports the conducted workflow, the multimodal test retains `image_url` through final
synthesis, the explicit tool-loop test preserves its single-worker response,
and the internal structured judge test performs exactly one provider call. Do
not claim provider-side semantic schema validity from HTTP 200.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*.
https://doi.org/10.48550/arXiv.2512.04388

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator*. https://doi.org/10.48550/arXiv.2512.04695

OpenAI. (n.d.-a). *Create chat completion*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/chat/create

OpenAI. (n.d.-b). *Create a model response*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/responses/create
