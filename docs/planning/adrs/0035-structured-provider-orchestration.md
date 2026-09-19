---
id: "0035"
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
    target: "every workflow call is recorded under one workflow_run_id, using provider counts when valid and the existing token counter otherwise"
    source: "tests/test_cost_router.py"
  - metric: "strict schema enforcement"
    target: "JSON Schema output validates locally; one governed repair per candidate is traced and virtual selectors advance through distinct eligible candidates before typed exhaustion"
    source: "tests/test_structured_output_distinct_fallback.py"
  - metric: "provider health continuity"
    target: "synthesis transport and repeated schema failures update the existing circuit ledger before a later independent request is routed"
    source: "tests/test_model_judge.py"
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
fields. Every evidence and synthesis call is written to the existing cost
ledger under one workflow run. Valid provider-reported usage is preserved;
calls whose provider omits usage use the same token-counting fallback as a
normal synchronous completion instead of disappearing from the ledger. Costs
are summed only when their currencies match.

Tool requests remain a single-provider exception because the client owns tool
execution state and OpenAI-compatible clients do not send a proprietary opt-in
header. The gateway therefore preserves the provider response instead of
inventing or merging tool calls. Direct Python callers retain the established
single-provider default; the authenticated HTTP boundary explicitly selects
the conducted path where it is safe.

Capability tags are positive declarations. A known vision-capable candidate is
preferred for image evidence; absence of any such declaration does not rewrite
an existing provider contract into a false claim of incompatibility.

For `json_schema`, provider acceptance of `response_format` is not proof that
the returned content conforms. The gateway selects the schema's declared JSON
Schema dialect, parses the final content, and validates the instance locally.
One invalid synthesis receives one same-candidate repair call with the original
schema. Both synthesis and repair remain distinct workflow trace and cost-ledger
steps even when they fail validation. An explicitly requested concrete model
then fails closed without changing identity. A virtual selector excludes that
candidate and may regenerate through the next distinct eligible candidate,
including another provider endpoint, while retaining the request's endpoint
scope, free/ZDR rules, capability gates, file replicas, candidate controls,
shared spend budget, and trace. Every candidate receives at most one synthesis
and one repair. Exhaustion is typed as `structured_output_exhausted` beneath the
stable public `invalid_structured_output` response code. There is no schema
weakening, item dropping, raw-output diagnostic, untraced repair, or recursive
retry multiplication. Provider transport and repeated schema failures update
the existing circuit ledger; success clears it.

## Consequences

- Structured outputs and Responses no longer bypass orchestration or cost
  provenance.
- Responses remain native at the final provider boundary, with explicit local
  transport translation where already supported.
- Structured requests consume additional test-time compute.
- A schema-violating virtual request may consume one synthesis and one
  auditable repair call per distinct eligible candidate before exhaustion.
- Tool execution cannot gain multi-agent verification until an OpenAI-compatible
  stateful tool-loop contract is implemented.

## Research artifact reuse and redistribution

This correctness repair does not introduce a new routing objective; it
restores ADR 0035's already-accepted bounded candidate-recovery semantics.
A repair-only request-size rejection retires that virtual candidate and
starts a fresh synthesis only on another already-eligible candidate; when
none remains, the request-size error remains the terminal classification
rather than being rewritten as structured-output exhaustion. Previously
excluded candidates are never retried.

The relevant routing literature is already committed in this repository as
redistributable artifacts: [`RouteLLM`](../../papers/routellm-routing-2406.18665.pdf)
and [`Hybrid LLM`](../../papers/hybrid-llm-query-routing-2404.14618.pdf).
Their cost/quality-aware routing evidence supports selecting among eligible
model candidates; it does not authorize bypassing caller endpoint, privacy,
or budget constraints. Conductor and TRINITY remain cite-link-summary
references in `docs/papers/README.md` because this repository has not
independently established a redistribution grant for those newer preprints;
duplicating their PDFs in this PR would therefore weaken, not strengthen,
the repository's copyright rule.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*.
https://doi.org/10.48550/arXiv.2512.04388

OpenAI. (n.d.). *Responses API reference*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/responses

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator*.
https://doi.org/10.48550/arXiv.2512.04695
