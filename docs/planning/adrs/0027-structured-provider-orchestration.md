---
id: "0027"
title: "Keep structured provider responses inside orchestration"
status: accepted
proposed_date: "2026-08-25"
accepted_date: "2026-08-25"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/cost_router.py"
  - "contextual_orchestrator/server.py"
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: constrained-by
  - path: "docs/planning/adrs/0021-reasoning-effort-profiles.md"
    relation: extends
success_criteria:
  - metric: "structured request orchestration"
    target: "non-null response_format and non-tool Responses requests retain conducted workflow lineage"
    source: "tests/test_openai_passthrough.py"
  - metric: "provider usage provenance"
    target: "every provider-reported workflow call is recorded under one workflow_run_id"
    source: "tests/test_cost_router.py"
---

# Keep structured provider responses inside orchestration

## Context

The gateway previously sent Chat `response_format` and every Responses request
directly to one provider. The wire response was compatible, but the request
silently skipped the product's conducted workflow, verification evidence, and
per-call cost provenance.

## Decision

Validated structured Chat and non-tool Responses requests use the existing
conducted workflow, followed by one provider-native synthesis call. The final
call retains the caller's endpoint, schema, tools, metadata, message order, and
multimodal parts. Internal evidence is not returned through mock/provider echo
fields. Provider-reported usage for each evidence and synthesis call is written
to the existing cost ledger under one workflow run; costs are summed only when
their currencies match.

Tool requests remain a single-provider exception because the client owns tool
execution state and OpenAI-compatible clients do not send a proprietary opt-in
header. The gateway therefore preserves the provider response instead of
inventing or merging tool calls. Direct Python callers retain the established
single-provider default; the authenticated HTTP boundary explicitly selects
the conducted path where it is safe.

Capability tags are positive declarations. A known vision-capable candidate is
preferred for image evidence; absence of any such declaration does not rewrite
an existing provider contract into a false claim of incompatibility.

## Consequences

- Structured outputs and Responses no longer bypass orchestration or cost
  provenance.
- Responses remain native at the final provider boundary, with explicit local
  transport translation where already supported.
- Structured requests consume additional test-time compute.
- Tool execution cannot gain multi-agent verification until an OpenAI-compatible
  stateful tool-loop contract is implemented.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*.
https://doi.org/10.48550/arXiv.2512.04388

OpenAI. (n.d.). *Responses API reference*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/responses

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator*.
https://doi.org/10.48550/arXiv.2512.04695
