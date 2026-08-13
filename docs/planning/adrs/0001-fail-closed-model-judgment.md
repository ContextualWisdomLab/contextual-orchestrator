---
id: "0001"
title: "Fail-closed structured model judgment"
status: accepted
proposed_date: "2026-08-10"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "contextual-orchestrator runtime"
  - "fast-mlsirm evaluation adapter"
informed:
  - "contributors"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "tests/test_model_judge.py"
  - "fast-mlsirm/python/fast_mlsirm/llm_judge.py"
effort: M
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0002-explicit-local-mlx-evaluation.md"
    relation: influences
  - path: "docs/planning/adrs/0003-keyverse-authentication-boundary.md"
    relation: informational
asr_triggers:
  - kind: performance
    evidence: "A judge adds a provider call and evaluation comparisons must measure real work."
    note: "The extra call is explicit in the trace and evaluation bypasses the response cache."
  - kind: maintainability
    evidence: "Heuristic verdicts mix language interpretation with orchestration control flow."
    note: "A strict JSON protocol gives one auditable decision boundary."
success_criteria:
  - metric: "heuristic verifier decisions"
    target: "zero keyword-based accept/reject decisions in production code"
    measurement_window: "every test and review of the merged change"
    source: "tests/test_model_judge.py and repository search"
  - metric: "invalid or unavailable model verdicts"
    target: "100% rejected without term fallback"
    measurement_window: "every conducted workflow"
    source: "structured judge parser and regression tests"
---

# Fail-closed structured model judgment

## Context

The verifier decision is a trust boundary: accepting a result changes the answer returned by a conducted workflow. Keyword matching is not a valid base judgment because it cannot reliably represent negation, quoted risks, Korean or other languages, or a report whose positive and negative evidence coexist.

> OrchestrationPolicy.verifier_judge is configured as "model"; unsupported keyword modes raise ValueError.
>
> _judge_verifier_output records "model judgment required; keyword matching is disabled" and never accepts from thinker/worker presence.
>
> _model_judge_verification accepts only an explicit JSON decision enum and returns rejection when the judge is unavailable or malformed.

## Decision Drivers

* Do not allow a lexical accident to approve or reject model work.
* Keep routing heuristics explicitly separate from semantic judgment; a capability hint may select a worker, but it cannot decide answer quality or verification.
* Preserve failover, circuit-breaker, and provider usage accounting for judge calls.
* Keep evaluation latency honest when response caching is enabled.
* Make the decision auditable and testable without adding a provider SDK.

## Considered Options

* Keep positive/negative term matching as the default.
* Permit free-form model replies and search for ACCEPT/REJECT.
* Require a structured model verdict, route it through normal orchestration failure handling, and fail closed.

## Decision Outcome

Chosen option: "Require a structured model verdict and fail closed".

| Driver | Term matching | Free-form keyword scan | Structured model verdict |
| --- | --- | --- | --- |
| Language/negation safety | poor | poor | explicit evidence-based assessment |
| Failure behavior | hidden fallback | ambiguous | rejected and observable |
| Runtime integration | cheap but bypasses semantics | extra call | normal _invoke path with usage |
| Evaluation truthfulness | cache-sensitive | cache-sensitive | cache-bypassed comparison |

The judge returns exactly one bounded, duplicate-free JSON object with `{"decision":"ACCEPT"|"REJECT","reason":"brief evidence-based reason"}`. Wrapper text, extra fields, duplicate keys, missing fields, parser-stressing input, provider failure, or an empty verifier report reject the workflow. The fast-mlsirm judge adapter also calls an injected contextual-orchestrator object and never calls a provider directly.

### Consequences

* Good, because keyword matching is removed from the production decision path and its false-positive/false-negative class has regression coverage.
* Good, because judge failover and usage are recorded through _invoke.
* Bad, because an unavailable local model can now reject a workflow instead of silently accepting a worker output.
* Bad, because a conducted local run pays for one additional judge completion.

### Confirmation

Run python3 tests/test_model_judge.py, the full contextual test suite, and the fast-mlsirm judge adapter test. Search the merged tree for verifier_positive_terms, verifier_negative_terms, and "terms" verifier modes; no production judgment path may remain.

## Pros and Cons of the Options

### Keep term matching

* Good, because it has no extra model call.
* Bad, because it misreads quoted risk language and language-dependent wording.
* Bad, because it makes a safety decision from substring presence rather than evidence.

### Free-form keyword scan of a model reply

* Good, because it is easy to retrofit.
* Bad, because explanations can contain both decisions and the scan is another heuristic.
* Bad, because malformed output is difficult to audit consistently.

### Structured model verdict (chosen)

* Good, because the protocol is small, strict, and observable.
* Good, because failure is explicit and fail-closed.
* Bad, because it requires a capable local judge and increases latency/token use.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Keyword matching was language- and context-unsafe. | Delete term-based verdicts; use strict model JSON and fail closed. | Implemented |
| Architecture notes described deterministic keyword scoring without explicitly limiting it to routing, which could be mistaken for a judgment fallback. | Describe the mechanism as capability-hint routing only, link this ADR, and retain the structured model-judge regression tests as the acceptance boundary. | Implemented 2026-08-12 |
| The judge previously bypassed failover/circuit/usage handling. | Call the judge through _invoke. | Implemented |
| compare_to_baseline could measure cache hits instead of provider work. | Use _dispatch directly for both measured arms. | Implemented |
| Core orchestration has no gold-answer quality metric. | Keep structural latency metrics honest and inject fast-mlsirm for rubric quality; do not invent a lexical proxy. | Adapter implemented; benchmark gate ongoing |
| Judge prompt/output can be malformed or truncated. | Use bounded JSON extraction, actionable mlx template guidance, and fail closed. | Implemented |
| A model can wrap a verdict, add fields, duplicate keys, or send parser-stressing text. | Parse the complete bounded response with an exact duplicate-free schema and exercise the parser with Hypothesis and Atheris; never repair or keyword-match it. | Implemented |
| The strict judge parser had invalid-enum, empty/non-string-reason, and maximum-size boundaries that were only exercised indirectly. | Add direct regression tests for each fail-closed parser boundary so future schema changes cannot turn malformed model output into a decision. | Implemented in current local head; exact-head CI/review follow-up required |
| An environment toggle could bypass the fast-mlsirm judge adapter even though the Goal requires all model judgments to cross contextual-orchestrator through that adapter. | Always attempt the injected fast-mlsirm adapter first; retain the strict contextual fallback only when the optional package is unavailable, and remove the runtime environment bypass. | Implemented in current local head; exact-head CI/review follow-up required |
| `ContextualOrchestratorJudge` passes `mode=` to its injected completion object, while the gateway's fast-mlsirm adapter accepted only `messages`, causing the real adapter path to fail closed before judging. | Accept and validate the mode keyword at the adapter seam and preserve it in the returned completion metadata; add a direct regression. | Implemented in current local head; exact-head CI/review follow-up required |
| A broken installed fast-mlsirm import could be mistaken for an absent optional package and silently fall back to a different judge path. | Treat only a genuinely absent top-level package as eligible for the strict contextual fallback; fail closed for broken fast-mlsirm imports and add a regression. | Implemented in current local head; exact-head CI/review follow-up required |
| The planning strategy values `template`/`generated` are not valid fast-mlsirm orchestration modes; passing one into the judge made the default conduct verification fail closed before a model call. | Keep the judge as one bounded `route` call through the gateway, independent of the workflow planning strategy, and record that mode in the trace. | Implemented in current local head; exact-head CI/review follow-up required |
| The gateway passed `accept_threshold` both to `ContextualOrchestratorJudge.__init__` and to `judge()`, but the public judge method accepts the threshold only at construction. | Match the injected fast-mlsirm public signature: configure the threshold once in the constructor and pass only the documented judge arguments. | Implemented in current local head; exact-head CI/review follow-up required |
| Local model capacity can make four workflow steps too slow. | Benchmark route/conduct and expose concurrency/template controls; optimize only from measured traces. | Ongoing |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A small local model emits malformed JSON. | medium | high | Disable thinking when needed, raise output cap, reject malformed output, record the reason. | maintainer |
| Strict rejection lowers availability. | medium | medium | Keep route mode available and provide explicit model/provider failover. | maintainer |
| A judge agrees with a bad verifier report. | medium | high | Use fast-mlsirm rubric evaluation and curated regression prompts; never treat the judge as ground truth. | evaluation owner |

## Rollback / Exit Strategy

Revert the implementation commit if the structured protocol causes unacceptable availability or latency, but retain this ADR and the test that forbids keyword matching. A rollback may restore a prior orchestration behavior only behind a separately approved ADR; it must not reintroduce keyword matching as an implicit fallback.

## Affected Components

* contextual_orchestrator/orchestrator.py
* tests/test_model_judge.py
* fast-mlsirm/python/fast_mlsirm/llm_judge.py
* local mlx benchmark commands and traces

## More Information

The decision follows the structured-output and evaluator/optimizer patterns in the local agentic-evaluation guidance. It is deliberately provider-neutral so mlx-lm remains the runtime provider and fast-mlsirm remains the calibration/evaluation layer.
