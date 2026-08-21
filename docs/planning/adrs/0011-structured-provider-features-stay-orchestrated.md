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
success_criteria:
  - metric: "structured requests using the multi-agent workflow"
    target: "100% of non-null response_format, tools, tool_choice, functions, function_call, and Responses requests"
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

The OpenAI-compatible boundary previously treated `response_format`, tools, and
the Responses API as a provider passthrough. That made a request look
successful while skipping the Thinker/Worker/Verifier/Synthesizer workflow.
Structured output and multimodal requests are still product work, not an
exception to the orchestration contract. A consumer must receive the same
workflow evidence, verification boundary, session lineage, and cost accounting
as a plain chat request.

## Decision

1. A non-null structured provider feature is an orchestration trigger, never a
   silent single-agent downgrade.
2. The request enters the existing conducted workflow. Intermediate steps use
   the original messages, including multimodal content, and the final
   synthesizer performs the provider-facing structured completion.
3. The final provider payload preserves validated tools and structured-output
   fields. Responses `text.format` is translated to the equivalent Chat
   `response_format` for the internal provider call, then the result is mapped
   back to the Responses shape.
4. `json_object` and `json_schema` are both first-class structured workflows.
   Schema validation remains fail-closed at the HTTP boundary; a provider
   success is not treated as semantic schema validity.
5. The workflow response exposes bounded orchestration metadata by default.
   Prompts, answers, images, tool arguments, secrets, and unbounded raw traces
   are not put into telemetry or the default response.
6. Tool execution loops are not fabricated by this decision. Provider tools are
   preserved for the final synthesized call; an actual execute-observe-replan
   loop requires a separate ADR and contract.

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
* Good: the final provider retains the capability fields it must interpret.
* Bad: structured requests consume more provider calls and can take longer than
  a plain routed request.
* Bad: tool execution remains a follow-up capability rather than being implied
  by merely forwarding a tool declaration.

## Confirmation

Run the focused structured-output and orchestration tests. Confirm that the
Responses JSON-schema test preserves the schema, the tools test reports the
conducted workflow, and the multimodal test retains `image_url` through final
synthesis. Do not claim provider-side semantic schema validity from HTTP 200.

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
