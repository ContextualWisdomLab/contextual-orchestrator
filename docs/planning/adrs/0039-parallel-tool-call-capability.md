---
id: "0039"
title: "Model discovery must record parallel tool-call capability"
status: accepted
proposed_date: "2026-08-31"
accepted_date: "2026-08-31"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/model_discovery.py"
  - "contextual_orchestrator/chat_capability.py"
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/provider_bootstrap.py"
related:
  - path: "docs/planning/adrs/0035-structured-provider-orchestration.md"
    relation: extends
  - path: "docs/planning/adrs/0034-anti-heuristic-routing-evidence.md"
    relation: constrained-by
success_criteria:
  - metric: "single-tool-call exclusion from orchestrator/free"
    target: "a model whose evidence says it accepts only one tool call at a time is not selected by the general free pool"
    source: "tests/test_model_discovery.py"
  - metric: "discovery-orchestrator agreement"
    target: "general_free_serving_candidates and TaskOrchestrator._is_general_free_agent reach the same conclusion for the same evidence"
    source: "tests/test_model_discovery.py"
  - metric: "runtime capability tag propagation"
    target: "ModelAgent tags carry tool_call:multi or tool_call:single when discovery provides the evidence"
    source: "tests/test_provider_bootstrap.py"
---

# Model discovery must record parallel tool-call capability

## Context

The `orchestrator/free` pool is used by the ContextualWisdomLab central review agents
(OpenCode, Noema, Strix) because it is the zero-cost, capability-blind pool. A model
that enters this pool must be able to handle arbitrary chat requests, including
multi-tool-call requests, without the caller knowing the model's limitations in
advance.

Issue [#940](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/940)
records a live NIM failure: `meta/llama-3.2-11b-vision-instruct` rejected a request
with `openai.BadRequestError: 400 ... This model only supports single tool-calls at
once!`. The model had already been excluded from the general free pool on vision-input
grounds by ADR 0035/0034, but the failure surfaced a broader gap: `DiscoveredModel`
carried no tool-call parallelism signal at all, so there was no honest way to keep a
single-tool-call model out of the general free pool even when the evidence was known.

## Decision

Add a `supports_parallel_tool_calls: bool | None = None` field to `DiscoveredModel`.

- `True` means the provider catalog explicitly lists `parallel_tool_calls` in
  `supported_parameters` (or a live probe returns a successful multi-tool response).
- `False` means the provider catalog or a probe clearly reports the model accepts only
  one tool call at a time.
- `None` means no evidence either way, preserving the "positive declarations" contract
  from ADR 0035: absence of a declaration must not be treated as a false claim of
  incompatibility.

The field is wired through the same capability-tag pipeline as input modalities and
privacy evidence:

- `is_general_chat_candidate` excludes a model whose evidence is `False`.
- `is_discovered_chat_candidate` passes the field from `DiscoveredModel`.
- `is_routable_discovered_model` rejects single-tool rows.
- `general_free_serving_candidates` excludes them from the blind `orchestrator/free` pool.
- `agent_from_discovered` and `provider_bootstrap.serving_tags_for_discovered` emit
  `tool_call:multi` or `tool_call:single` tags.
- `TaskOrchestrator._is_general_chat_agent` derives the value from the runtime tags and
  passes it to `is_general_chat_candidate`.
- `TaskOrchestrator._is_general_free_agent` additionally refuses agents tagged
  `tool_call:single`.

A new `probe_discovered_model_tool_call_capability` function performs a minimal live
`POST /chat/completions` probe with `parallel_tool_calls: true` and two tool
definitions. It is deliberately separate from `discover_all_models` so callers decide
when the extra latency and token cost are justified. A successful response returns
`True`; a 400 whose body contains an explicit single-tool-call message returns `False`;
any network, auth, or ambiguous error returns `None` so the pool stays open rather
than excluding a model on a flaky probe.

## Consequences

- The general `orchestrator/free` pool can no longer route arbitrary multi-tool requests
  to a model known to support only single tool calls.
- Provider catalog evidence is the primary source; runtime probing is a deliberate,
  opt-in secondary source for providers that do not publish the parameter.
- Existing models whose evidence is `None` keep their previous eligibility, avoiding
  false negatives.
- The `.github` sidecar must still be updated to consume `general_free_serving_candidates`
  and preserve `input:` and `tool_call:` tags when it builds its own CI review catalog;
  that is a follow-up change in `ContextualWisdomLab/.github`.
