---
id: "0006"
title: "Calibrate polytomous LLM judgment against category and prompt bias"
status: accepted
proposed_date: "2026-08-11"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "fast-mlsirm LLM judge adapter"
  - "fast-mlsirm IRT response research"
  - "local Zotero literature collection"
informed:
  - "contributors"
affected_components:
  - "fast-mlsirm/python/fast_mlsirm/llm_judge.py"
  - "fast-mlsirm/tests/test_llm_judge.py"
  - "contextual_orchestrator/orchestrator.py"
  - "docs/benchmarks/"
  - "docs/planning/adrs/"
effort: M
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: influences
  - path: "docs/planning/adrs/0005-irt-response-matrix-contract.md"
    relation: influences
asr_triggers:
  - kind: security
    evidence: "Absolute LLM scoring can shift under rubric order, score identifiers, reference scores, user framing, and answer-option order."
    note: "Perturbation deltas are recorded instead of assuming one prompt is unbiased."
  - kind: maintainability
    evidence: "The user reports a positive tendency as the number of choices grows, but current literature does not prove a monotone LLM-specific effect."
    note: "Treat the claim as a measured hypothesis and fail the benchmark gate on material positive drift."
  - kind: performance
    evidence: "A calibration design that calls a judge must preserve contextual-orchestrator routing, tracing, and local-model controls."
    note: "The fast adapter accepts an injected orchestrator and adds no provider-specific transport."
success_criteria:
  - metric: "category-count score drift"
    target: "the same answer and rubric are evaluated at K in {2,3,5,7}; mean score and acceptance deltas are reported with uncertainty"
    measurement_window: "every polytomous calibration benchmark"
    source: "contextual-orchestrator traces and fast-mlsirm result records"
  - metric: "prompt perturbation invariance"
    target: "rubric order, score-ID labels, reference presence, answer-option order, and positive/negative framing are paired and compared"
    measurement_window: "every judge calibration release"
    source: "benchmark artifacts and regression reports"
  - metric: "IRT-safe output"
    target: "only multi-item dichotomous or explicitly categorized polytomous rows reach fast-mlsirm"
    measurement_window: "every IRT conversion"
    source: "ADR 0005 validator and tests"
---

# Calibrate polytomous LLM judgment against category and prompt bias

## Context

Polytomous judgment introduces more than an IRT data-shape problem. A judge
must map evidence to ordered categories, and the category labels, rubric
order, reference examples, response-option order, and user framing can all
become unintended cues. The user’s hypothesis that more choices can make an
LLM more positive is therefore a high-value risk, but it must be tested rather
than encoded as an unverified universal law.

> The local copy of Evaluating Scoring Bias in LLM-as-a-Judge reports scoring shifts caused by rubric order, score identifiers, and reference-answer scores.
>
> The local copies of the ICLR and NAACL studies report LLM selection or position bias under option changes, including experiments with different option counts and reordered choices.
>
> The local sycophancy study reports more positive feedback when user framing signals that a passage is liked, so agreement and politeness cannot be treated as evidence of quality.

## Decision Drivers

* Separate direct evidence of bias from the specific monotonic-positive hypothesis.
* Avoid making a multi-category choice list the sole source of an ordinal score.
* Keep judgment semantic and evidence-based; keyword matching remains forbidden.
* Preserve contextual-orchestrator routing for every fast-mlsirm judge call.
* Produce a repeatable benchmark that can distinguish category information from
  category-induced positivity.

## Considered Options

* Use a single K-way score prompt and assume more categories add useful information.
* Collapse every judgment to a binary keyword or lexical match.
* Use structured criterion scoring with fixed anchors, derive acceptance in the
  runtime, and run paired category/prompt perturbation calibration.
* Replace the local judge with a hosted evaluator without perturbation checks.

## Decision Outcome

Chosen option: "Use structured, criterion-level scoring plus perturbation
calibration; never assume that more categories are better or neutral".

| Driver | Single K-way score | Keyword fallback | Structured calibrated judge |
| --- | --- | --- | --- |
| Semantic validity | medium | poor | high |
| Category-count bias visibility | low | none | explicit deltas |
| Language/negation robustness | medium | poor | model evidence with strict schema |
| IRT compatibility | ambiguous | binary-only and invalid as a default | explicit multi-item projection |
| Local runtime integration | simple | bypasses judge semantics | contextual-orchestrator trace |

The default judge prompt keeps criterion-level scores, explicitly says not to
reward answer length, politeness, agreement, or a larger number of response
options, and derives accepted from the numeric score in the adapter rather
than trusting a redundant model boolean. A result can be projected into an
IRT row only through the multi-item contract in ADR 0005.

The calibration benchmark must evaluate the same semantic case under K values
2, 3, 5, and 7, balanced category labels and rubric orders, with and without
reference examples, and with positive/negative/neutral framing controls. It
must report score mean, category occupancy, acceptance rate, pairwise
agreement, and the signed shift from a human or deterministic gold label when
available. A positive shift with more categories is a failure signal, not a
normalization target.

The first end-to-end local MLX sweep is recorded in
`docs/benchmarks/2026-08-11-polytomous-llm-judge.md`. With the same worker
answer and rubric, the observed derived scores were 1.00, 0.75, 0.50, and
0.9167 for K=2,3,5,7, with acceptance changing across the sweep. This is not
evidence of a monotone positive effect; it is evidence that category-count
sensitivity is real enough to block an uncalibrated IRT interpretation.

The same run also exposed provider-format failure modes: a local model emitted
numeric criterion keys, copied an instruction phrase into a JSON key, and
returned decimal values for integer categories. The fast adapter now uses an
exact literal schema containing the validated criterion IDs and explicit
ordered anchors, accepts only mathematically integral category values, and
rejects the rest without keyword or positional repair.

For future high-stakes polytomous use, add cumulative threshold judgments or
another ordinal construction that does not ask the model to pick one of many
score IDs. This is a follow-up implementation direction, not a claim that
equal-width bins are unbiased.

### Consequences

* Good, because the suspected positive drift becomes measurable and
  reproducible instead of being hidden in an aggregate score.
* Good, because score-ID and rubric-order perturbations are treated as
  first-class regression cases.
* Good, because the fast-mlsirm adapter remains provider-neutral and every
  call is visible in contextual-orchestrator traces.
* Bad, because calibration costs additional local model calls and requires
  gold or human comparisons for strong conclusions.
* Bad, because a small local model can fail to emit valid structured output;
  malformed output remains rejected rather than repaired lexically.

## Pros and Cons of the Options

### Single K-way score

* Good, because it is easy to prompt and cheap to implement.
* Bad, because score-ID and category-count effects can be mistaken for quality.
* Bad, because it does not distinguish an ordinal response from a model’s
  arbitrary numeric preference.

### Keyword fallback

* Good, because it is cheap.
* Bad, because it violates the explicit user requirement and fails on
  negation, multilingual evidence, and mixed reports.
* Bad, because it cannot measure an ordered latent trait.

### Structured calibrated judge (chosen)

* Good, because it retains semantic evaluation while exposing perturbation
  sensitivity.
* Good, because criterion scores become explicit multi-item candidates for
  ADR 0005 rather than a hidden scalar.
* Bad, because calibration is more expensive than one unchallenged call.

### Hosted evaluator

* Good, because it may produce stronger raw judgments.
* Bad, because it violates the local-model performance objective and does not
  remove category or prompt bias automatically.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| A local judge returned inconsistent score and accepted fields during a real MLX run. | Derive acceptance from the validated numeric score; reject non-JSON or non-boolean fields, never keyword-repair. | Implemented |
| A local category judge emitted numeric keys, instruction text as a key, and decimal category values. | Prompt an exact literal schema with criterion IDs and anchors; accept integral JSON numbers only and reject malformed output. | Implemented |
| The positive-with-more-options hypothesis lacks a direct monotonic LLM proof. | Add K=2/3/5/7 paired calibration and treat positive drift as a gate failure. | Required next |
| A real K=2/3/5/7 sweep changed the same case’s derived score and acceptance. | Keep category projection experimental, report the complete sweep, and block production IRT claims until replicated calibration is stable. | Implemented as benchmark; gate ongoing |
| Score IDs and rubric order can change absolute judgments. | Randomize or balance labels/order and record signed perturbation deltas. | Required next |
| User framing can induce positive or negative sycophantic feedback. | Add neutral, liked, disliked, and authored framing controls; compare to content-only gold. | Required next |
| Equal-width score bins can create artificial polytomous thresholds. | Implement cumulative threshold judging or calibrated category mapping before production IRT use. | Ongoing |
| Multiple criteria can still be correlated or cover one latent dimension poorly. | Require item coverage review, factor anchors, and sample-size checks before interpreting IRT fit. | Required next |
| A single judge call can hide model drift. | Preserve contextual-orchestrator trace, model identity, prompt variant, category count, and usage in benchmark records. | Implemented in adapter trace and the 2026-08-11 benchmark artifact |
| A one-person, two-item matrix can pass a shape check while remaining insufficient for IRT estimation. | Require multiple persons, item-information, and factor-coverage checks before fitting or interpreting an IRT model. | Required next |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| Calibration cost is too high on local hardware. | high | medium | Use a bounded paired suite and reuse fixed cases; do not omit the perturbation axes that define the risk. | evaluation owner |
| A prompt instruction suppresses but does not measure bias. | high | high | Keep perturbation experiments and report deltas; prompt wording alone is not evidence of neutrality. | evaluation owner |
| Positive framing is confused with answer quality. | medium | high | Use content-only gold labels and neutral controls; keep sycophancy as a separate metric. | evaluation owner |
| Category projection is used as a validated IRT instrument too early. | medium | high | ADR 0005 rejects scalar/one-item input and this ADR blocks uncalibrated category claims. | maintainer |

## Rollback / Exit Strategy

If a mitigation prompt reduces agreement with gold labels, roll back only that
prompt revision and keep the perturbation benchmark. Do not roll back to
keyword matching or to an unobserved single K-way score. If cumulative
threshold judging is not implemented, keep equal-width projection explicitly
experimental and do not use it for a production IRT claim.

## Affected Components

* fast-mlsirm/python/fast_mlsirm/llm_judge.py
* fast-mlsirm/tests/test_llm_judge.py
* fast-mlsirm/python/fast_mlsirm/irt_contract.py
* contextual-orchestrator orchestration, trace, and local-MLX benchmark paths
* docs/benchmarks/ and future category-bias reports

## More Information

The local Zotero collection was searched through the running Zotero Local
Connector API. It now contains the relevant records and four accessible OA
PDF attachments: Li et al. item SHLVYKJC with attachment TVZMTEB8; Zheng et
al. item GSZ4D83U with attachment J44YVR37; Pezeshkpour and Hruschka item
UFZQ8WN6 with attachment S5KQCN97; and Sharma et al. item YDM7VXSG with
attachment 47VH4PC7. Response-category records MYPNHHWJ and CWY355RP were
also added for the psychometric comparison. The Iannario and Jones--Loe
records are OA metadata records with their publisher PDF URLs retained; the
local Connector could not download those two originals during this run
(De Gruyter returned an empty 202 response and SAGE returned an anti-bot 403).
They remain explicit follow-up attachment work rather than being represented
by fabricated or regenerated PDFs.

Primary sources:

* https://arxiv.org/abs/2506.22316
* https://proceedings.iclr.cc/paper_files/paper/2024/hash/54dd9e0cff6d9214e20d97eb2a3bae49-Abstract-Conference.html
* https://aclanthology.org/2024.findings-naacl.130/
* https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models
* https://www.degruyterbrill.com/document/doi/10.1515/ijb-2021-0013/html
* https://journals.sagepub.com/doi/10.1177/2158244013489691
