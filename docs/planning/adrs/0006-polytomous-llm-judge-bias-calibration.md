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
  - metric: "local judge service reliability"
    target: "every compared model reports bounded latency, timeout, structured-parse success, token usage, and score drift; a timeout or malformed response is a failed comparison, not an omitted datum"
    measurement_window: "every local-model calibration benchmark"
    source: "contextual-orchestrator traces and benchmark records"
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

After the prompt was made explicit about JSON-only output, no markdown fences,
integer category values, and a numeric top-level score, the same Gemma 4B case
was repeated twice at each K. All eight calls parsed successfully through the
contextual-orchestrator route. Mean scores were 0.50, 0.50, 0.00, and 0.75 for
K=2, 3, 5, and 7; acceptance counts were 0/2, 0/2, 0/2, and 2/2. The result
reproduces category-count sensitivity but is non-monotonic, so it is not
evidence for a universal positive-with-more-options law.

A separate three-criterion case compared the cached Gemma 31B judge at the
same K values. Its derived score stayed at 0.3333 and acceptance stayed 0/2 at
every K, while the criterion categories moved with K; the eight responses all
parsed successfully. The cached 32B DeepSeek judge did not produce a
structured response within the 180-second request bound on its first K=2 call,
so the comparison was stopped and no quality conclusion was drawn for it.
This adds a reliability gate: the largest or most capable-looking local model
is not a performance win if it cannot return a bounded, parseable judge result.

For high-stakes polytomous use, the fast adapter now provides an explicit
`category_method="cumulative_threshold"` mode and a bounded
`category_method="binary_threshold"` mode with an explicit `category_count`.
The binary method asks the model whether each criterion clears each ordered
boundary, validates the Boolean responses as monotone, and derives the
category from the number of cleared thresholds. When callers provide
`category_count` without a method, binary thresholds are now the default;
direct K-way output remains an explicit calibration-only choice. This reduces
dependence on one K-way score-ID choice, but it does not make the judge
unbiased: the same answer must still be calibrated across K, prompt
perturbations, models, and gold labels.

The first direct-versus-threshold extension run on 2026-08-12 used the same
Gemma 4 e4b MLX judge, worker answer, two criteria, disabled thinking,
temperature 0, two repeats per K, and the same contextual-orchestrator route.
All 16 responses parsed and produced two-item polytomous rows accepted by the
ADR 0005 validator. Direct K-way scores were 1.0000 at K=2,3,5,7; cumulative
threshold scores were 1.0000, 1.0000, 0.5000, and 0.3333 respectively, with
acceptance changing from yes to no at K=5. This is a useful replication of
category-method sensitivity, not evidence of a universal directional bias.

A second 2026-08-12 replication used the cached local Llama 3B judge under
neutral, liked, and disliked framing for one good and one unsafe release plan.
The good plan parsed in 11/18 calls and was accepted in 5/11 parsed calls; the
unsafe plan parsed in all 18 calls and was rejected in every case. Direct K-way
judging parsed 8/9 good-plan calls, while cumulative thresholds parsed 3/9.
The good-plan direct scores were framing-sensitive at K=7 (neutral `0.5833`,
liked/disliked `0.8333`) but equal at K=5 (`0.7500`), and the K=2/K=7 path was
not monotone. Seven good-plan failures were retained as failures: five invalid
JSON responses, one out-of-range category, and one non-monotone threshold
vector. This is evidence of local-model format and framing sensitivity, not a
universal positive-choice-count law.

A same-route retry probe then evaluated a separate good release plan with the
same 3B model, two criteria, K in `{2,5,7}`, and neutral/liked/disliked
framing. All nine direct K-way responses parsed, but scores were respectively
`(0.0000, 1.0000, 0.8333)`, `(0.0000, 1.0000, 0.9167)`, and
`(0.0000, 0.7500, 1.0000)`. Four cumulative-threshold calls at K in
`{2,3,5,7}` each failed strict parsing; one identical second
contextual-orchestrator completion per failure recovered none. K=2 failed the
boundary-array shape contract, while K=3/5/7 failed monotonicity. This probe
does not justify a blind retry: any future recovery must be independently
specified, remain on the contextual-orchestrator path, retain first/final
parse status and cost, and accept only a final strict schema result.

The binary-threshold calibration method was subsequently optimized at
fast-mlsirm exact commit `61e6be9`: when the injected contextual-orchestrator
exposes its already-bounded `client.local_concurrency`, independent boundary
calls reuse that limit. Generic injected orchestrators remain sequential by
default. This is a transport/latency optimization only; it does not reorder
criteria in the retained evidence, repair malformed output, infer a threshold,
or change the fail-closed monotonicity rule. The live MLX follow-up retained
both valid and failed cases, including unsafe K=5/K=7 results at `5.756/7.719 s`
and `2,422/3,620` tokens, while safe K=5/K=7 remained non-monotone failures.

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
| A local Llama 3B judge emitted a non-numeric top-level `score` alongside integer category values; ignoring the redundant field would weaken the strict schema. | Validate the redundant top-level score's finite numeric shape, but derive the effective score and acceptance only from validated criterion categories; reject malformed fields without repair. | Implemented |
| The positive-with-more-options hypothesis lacks a direct monotonic LLM proof. | Add K=2/3/5/7 paired calibration and treat positive drift as a gate failure. | Required next |
| A real K=2/3/5/7 sweep changed the same case’s derived score and acceptance. | Keep category projection experimental, report the complete sweep, and block production IRT claims until replicated calibration is stable. | Implemented as benchmark; gate ongoing |
| A prompt-hardened two-repeat K=2/3/5/7 sweep parsed reliably but remained non-monotonic (K=5 below K=2/3; K=7 above them). | Keep strict parsing and report replication variance; expand balanced cases, criterion/rubric order, answer-option count/order, framing, and model variants before drawing a directional bias conclusion. | Required next |
| Score IDs and rubric order can change absolute judgments. | Randomize or balance labels/order and record signed perturbation deltas. | Required next |
| User framing can induce positive or negative sycophantic feedback. | Add neutral, liked, disliked, and authored framing controls; compare to content-only gold. | Required next |
| Equal-width score bins can create artificial polytomous thresholds. | Implement cumulative threshold judging or calibrated category mapping before production IRT use. | Ongoing |
| A K-way prompt can make the model choose among many score identifiers even when the underlying evidence is unchanged. | Expose opt-in cumulative-threshold judging with explicit K, exact Boolean arrays, monotonicity validation, derived categories, and the same multi-item IRT validator; keep direct K-way output experimental until paired calibration supports it. | Implemented on fast-mlsirm follow-up PR; calibration ongoing |
| A fresh same-route 3B MLX direct probe scored the unsafe case `0.0`, `0.5`, `0.8333` and the partial-evidence case `0.0`, `1.0`, `0.0` at K=`2,5,7`; acceptance therefore changed with the number of score identifiers | Resolve an omitted method to bounded binary thresholds whenever `category_count` is present; retain direct K-way only for explicit calibration and record every semantic miss as failed evidence rather than repairing it | Implemented in fast-mlsirm follow-up; exact-head review required |
| The paired binary probe returned score `0.0` for both safe and unsafe answers at K=`5,7`, avoiding the direct positive drift in this sample but under-recognizing the safe answer | Keep the default fail-closed and require held-out human/gold recall, category occupancy, and parse/provider denominators before treating any local model/prompt as IRT-ready; do not claim bias removal from this probe | Observed 2026-08-14; calibration gate remains open |
| The real `_FastMLSIJudgeAdapter` path with fast-mlsirm `9d18f53` and contextual-orchestrator `a0a354a` selected binary thresholds when K=5 was supplied without a method: the unsafe case produced a valid rejected `(0,0)` result in 8 calls, while the safe case failed monotonicity after 8 calls | Treat the integrated unsafe result as contract evidence only and retain the safe failure as a calibration datum; keep malformed/non-monotone output fail-closed, record trace/usage/latency, and require held-out human/gold recall before IRT production | Observed 2026-08-14; integrated default verified, semantic calibration remains open |
| The real MLX safe-case failure was initially only the text `criterion thresholds must be monotone`, but fast-mlsirm `d1eca0c2fed89991e647802f0b27a91f0f6fe2bd` captured `semantic_status=non_monotone`, `parse_status=passed`, `8/8` completed calls, `8` trace steps, and `2,639` provider tokens in bounded exception evidence | Keep complete semantic failures in the denominator and separate non-monotonicity from provider/parse failures; retain ordered records and usage without retry, keyword matching, positional repair, or IRT coercion | New evidence 2026-08-14; failure-evidence contract implemented, calibration remains open |
| A fresh anchored K=5 probe through the real adapter showed Gemma 4 e4b returning strict `(4,4)`/score `1.0` in `3,031` tokens and `11.96 s`; the same rubric left Llama 3B with repeated safe false negatives and Llama 1B with eight malformed boundary responses | Compare judge models on balanced gold cases using semantic recall, false-positive/false-negative rates, parse/provider denominators, category occupancy, latency, and usage; use the stronger result as a candidate only, never as a universal bias correction | New evidence 2026-08-14; fast-mlsirm `dd44a95`, model calibration remains open |
| The binary prompt previously allowed a K-only ordinal interpretation with no criterion-specific definitions, so the model could not reliably distinguish intermediate categories even when the answer contained operational controls | Allow complete per-criterion `category_anchors` of length K, bind each boundary to its matching anchor as untrusted rubric data, record anchor presence, and keep omitted-anchor runs exploratory rather than treating them as calibrated IRT evidence | Implemented in fast-mlsirm `dd44a95`; held-out anchor/gold calibration required |
| A cumulative-threshold prompt can still produce inconsistent or non-monotone boundary judgments, and its score can differ from direct K-way output. | Reject non-Boolean, wrong-length, or false-then-true vectors; record category method, K, trace, usage, parse success, score, acceptance, and perturbation deltas in every benchmark. | Implemented in adapter/tests; calibration ongoing |
| Multiple criteria can still be correlated or cover one latent dimension poorly. | Require item coverage review, factor anchors, and sample-size checks before interpreting IRT fit. | Required next |
| A single judge call can hide model drift. | Preserve contextual-orchestrator trace, model identity, prompt variant, category count, and usage in benchmark records. | Implemented in adapter trace and the 2026-08-11 benchmark artifact |
| A one-person, two-item matrix can pass a shape check while remaining insufficient for IRT estimation. | Require multiple persons, item-information, and factor-coverage checks before fitting or interpreting an IRT model. | Required next |
| A larger local judge can preserve the aggregate score while moving criterion categories, and a cached 32B judge timed out before producing structured output. | Gate model comparisons on bounded latency, timeout rate, strict-parse success, token usage, category occupancy, and score/acceptance drift; never treat a timeout as a missing or positive result. | Implemented in the 2026-08-12 benchmark; reliability calibration ongoing |
| A cached local 3B judge failed to emit valid or ordinally coherent structured output in 7/18 good-plan calls, and framing changed some K=7 scores. | Keep every malformed/monotonicity failure in the denominator; compare a separately measured bounded retry or stronger local judge only through contextual-orchestrator, and never add keyword, positional, or silent-drop repair. | Recorded in the 2026-08-12 benchmark; reliability/framing calibration required |
| An identical second contextual-orchestrator completion recovered none of four cumulative-threshold failures in a follow-up 3B probe, while direct K-way scores shifted across K and framing. | Keep blind retry out of the production contract. If recovery is pursued, compare a bounded independent binary-threshold decomposition or stronger local judge on held-out paired cases, record added latency/tokens and first/final parse status, and preserve strict fail-closed parsing. | Measured 2026-08-12; Goal expanded and calibration required |
| A live bearer-authenticated gateway probe on the same Llama 3B answer and two criteria at `K=5` produced direct `1.0000` (`4/4`, accepted) versus cumulative-threshold `0.0000` (`0/0`, rejected), with both strict parses valid and one contextual-orchestrator trace step each. | Treat this as paired method sensitivity, not as a positive-bias conclusion. Keep method/K/trace/usage in the denominator, compare balanced held-out cases, and retain the multi-item polytomous validator; never repair the disagreement lexically or positionally. | New evidence 2026-08-12; calibration required |
| A fresh two-case 3B MLX probe through contextual-orchestrator produced direct scores of `0.5 -> 1.0 -> 1.0` for a safe release plan and `0.0 -> 0.0 -> 0.3333` for an unsafe plan at K `2,5,7`; cumulative thresholds parsed only at K=5 and failed JSON/monotonicity at K=2/7. | Preserve all 12 comparisons, including four strict-parse failures, in the denominator. Do not promote direct or cumulative to an unbiased default; add an opt-in bounded binary-threshold decomposition and compare its latency, calls, tokens, semantic recall, and human/gold agreement on held-out paired cases. | New evidence 2026-08-14; Goal/ADR expanded, calibration remains required |
| The binary-threshold follow-up reduced each boundary to a Boolean contextual-orchestrator call, but the safe case still failed monotonicity at K=5/7 while the unsafe case parsed at score `0.0` using 8/12 calls and `2,606/3,940` tokens. | Keep binary decomposition experimental and fail-closed. Record its call budget and semantic under-recognition; do not short-circuit, synthesize, or repair higher categories without an explicit ordinal measurement design and held-out gold evidence. | New evidence 2026-08-14; method implemented, calibration required |
| OA metadata, local Zotero attachment state, and network retrievability are separate: Zotero `9.0.6` exposes read-only Local API reads; the official Jones--Loe SAGE PDF returned anti-bot `403`; the official Iannario De Gruyter PDF returned a WAF `202` response with zero bytes; and Zotero items `CWY355RP`/`MYPNHHWJ` have no child attachment. | Record rights, canonical landing/PDF URLs, and retrieval evidence separately. Attach only byte-verified original PDFs through an authorized Zotero/API route, and retry from an authorized route or a write-capable Zotero version. Never regenerate, OCR-rebuild, or substitute a PDF while claiming it is the original. | Required follow-up |
| OpenAlex/Unpaywall/Crossref revalidation identifies Jones--Loe as gold OA with CC BY metadata and Iannario as a CC BY 4.0 published version; local Zotero rights fields agree (`Open access` and `Creative Commons Attribution 4.0 International`), but neither record has a child attachment. The Cao et al. AAAI-26 study also shows substantial option-only answer bias when the question is removed, with contamination more explanatory than position or answer popularity. | Keep Jones--Loe and Iannario citation-only until an authorized route yields byte-verified original parent attachments; never count 403/202 HTML, reconstructed files, or unauthorized mirrors. Add option-only/no-question, shuffled-option, replaced-distractor, and contamination-aware controls so a positive score at larger `K` is not misattributed to option count. Keep Cao citation-only because its PDF is all-rights-reserved. | Revalidated and expanded 2026-08-14; rights are corrected, while PDF retrieval and calibration controls remain required |
| Follow-up OA retrieval found a rights/access conflict for Iannario: the [De Gruyter article](https://www.degruyterbrill.com/document/doi/10.1515/ijb-2021-0013/html) and Crossref/OpenAlex metadata state CC BY 4.0, while the [IRIS record](https://www.iris.unina.it/handle/11588/877609) labels its editorial PDF authorized-users-only and [RePEc](https://ideas.repec.org/a/bpj/ijbist/v18y2022i2p593-611n2.html) reports full-text restriction. The [SAGE Jones--Loe PDF](https://journals.sagepub.com/doi/pdf/10.1177/2158244013489691) remains publisher-original but returned anti-bot 403 to the local downloader. | Treat the license and retrieval state as separate fields; do not attach either binary until an authorized route produces a byte-verified original and the rights are reconciled. Do not use ResearchGate, a WAF/HTML response, OCR, or a reconstructed PDF as the claimed original. | Rechecked 2026-08-14; PDF attachment remains an explicit Goal item |
| Before this follow-up, fast-mlsirm had no bounded reusable control that ran baseline, option-only/no-question, shuffled-option, and distractor-replacement variants through the existing contextual-orchestrator judge while retaining provider/parse/IRT failures and gold agreement. | Implement `JudgeCalibrationCase`/`JudgeCalibrationReport` and run every variant through an injected `ContextualOrchestratorJudge`; preserve contamination status, caller-supplied gold categories, multi-criterion polytomous rows, trace/usage, and every failure. Do not retry, repair, keyword-match, infer category positions, or interpret score deltas as causal option-count bias. | Implemented in fast-mlsirm at exact head `5a072705c840ea70d87a73bf737d5b193ef428cb` 2026-08-14; exact-head review/check follow-up required |
| A Gemma 4 e4b loopback smoke through the new paired controls completed four variants for both 3-option and 5-option cases at K=`3`; all 8 rows were `[2,2]`, all 8 matched the held-out gold categories, and every paired score delta was `0.0` (`20.442 s/7,868` and `20.277 s/8,110` provider tokens). | Record this as a bounded integration and negative-observation smoke only. Expand persons/items, correct-option positions, option counts, models, framing, contamination controls, and human/gold anchors before estimating or rejecting a general positive option-count effect or IRT readiness. | Observed 2026-08-14; semantic bias calibration remains open |
| A same-case K=`3` model comparison through the real MLX route gave 1B Llama `0/4` passed with four bounded JSON/format failures; 3B Llama `4/4`, gold `4/4`, all deltas `0.0`, `24.139 s`, `7,960` tokens; Gemma 4 e4b `4/4`, gold `4/4`, all deltas `0.0`, `39.731 s`, `7,860` tokens. | Treat 1B as a structured-output reliability failure for this prompt, and 3B/Gemma as candidate models only. Expand balanced persons/items, option positions/counts, framing, contamination controls, and human/gold anchors before model promotion or IRT interpretation; latency/token differences are workload evidence, not quality proof. | Observed 2026-08-14; semantic calibration remains open |
| `ContextualOrchestratorJudge` previously validated only that an injected object had `complete()`, leaving a direct-provider or unrelated transport possible even though every Judge call is required to use contextual-orchestrator. | Require the exact `contextual-orchestrator-contract-v1` provenance marker before construction, expose it from `_FastMLSIJudgeAdapter`, and reject unmarked transports before any call. Marked test doubles are contract tests only and do not loosen production routing. | Fixed in the current cross-repository follow-up; focused tests and exact-head review/check follow-up required |
| A fresh held-out Gemma 4 e4b paired calibration through the exact contextual-orchestrator route returned the highest category `[2, 2]` for baseline, option-only, shuffled-option, and replaced-distractor variants; all four passed and matched gold, but every criterion was saturated and every paired score delta was `0.0` (4 rows, 7,626 provider tokens). | Treat this as ceiling saturation, not evidence of no positive-choice-count bias or judge neutrality. Add per-criterion category-occupancy reporting, expand difficult/partial/unsupported gold items and option-count/position/model strata, and block IRT interpretation until held-out recall, false-positive rates, and non-ceiling occupancy are demonstrated. Never repair, keyword-match, or collapse saturated rows into a favorable result. | Observed 2026-08-14 on contextual `7f47665f0d837debc9db82060347ff3502469239` + fast `830d3c0c159a52a5131859dd549b0d89f8b9d02d`; Goal/ADR expanded, occupancy implementation and calibration follow-up required |
| A fresh live K=`3` anchored comparison through contextual-orchestrator found e4b produced valid safe `[2,2]` and unsafe `[1,1]` rows, while 3B failed the unsafe case as non-monotone, 31B failed the safe boundary after `96.93 s`, and DeepSeek completed zero of eight boundary groups within about `100 s` each. | Use evidence-based role eligibility: exclude 31B, DeepSeek, and the previously failing 1B from `verifier`; select e4b as the current primary and keep 3B as an explicit lower-priority candidate. Preserve all semantic, parse, timeout, and latency failures; this is not a bias correction or IRT-readiness claim, and larger balanced gold/perturbation calibration remains mandatory. | Observed 2026-08-14; Goal/ADR expanded, contextual routing updated, calibration remains open |
| A balanced held-out K=`3`/K=`7` edge-position run through contextual-orchestrator `d3480cc` and fast-mlsirm `dbbd41d` covered first/last correct-option positions and four presentation variants. It produced 11 valid `[2,2]` rows and 5 strict `JudgeFormatError` failures across 16 paired outcomes/64 boundary calls; every valid criterion was at ceiling category `2`, only one group had a complete baseline/control comparison, and elapsed time was `1,044.7 s`. | Treat the result as ceiling-saturated, incomplete reliability evidence: preserve all five failures, do not infer neutrality or positive option-count bias from `11/11` conditional gold agreement, and do not interpret the rows as IRT-ready. Add harder partial/unsupported gold items, non-ceiling anchors, more persons/items/models, balanced option counts/positions, and an explicit completion-time budget before the next calibration gate. | New evidence 2026-08-14; Goal/ADR expanded, bias calibration and completion-path reliability remain open |

| A dedicated-port Gemma 4 e4b run through contextual-orchestrator `63451a0` and fast-mlsirm `3c2fecf` evaluated partial and unsupported held-out answers at K=`3`/K=`7` with edge correct-option positions and four controls. It produced 15 passed and 1 strict non-monotone failure across 16 outcomes/128 boundary calls in `202.781 s`; conditional gold exact agreement was `5/15`. Evidence-quality occupancy covered categories 0/1/2 evenly, but risk-awareness had occupancy `{0:7,1:0,2:8}`. Option-only controls raised unsupported evidence quality from 0 to 1 and partial baselines were mostly over-scored `[2,2]` against gold `[1,1]`. | Keep all outcomes, semantic failures, and control deltas in the denominator; treat this as evidence of semantic miscalibration and control sensitivity, not a positive-K causal estimate or IRT-ready dataset. Add harder intermediate risk anchors, more human/gold items and persons, model/position/count/framing strata, and a completion-time budget before verifier promotion. No keyword matching, retry, repair, positional inference, or silent drop. | New evidence 2026-08-14; Goal/ADR expanded, semantic calibration remains open |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| Calibration cost is too high on local hardware. | high | medium | Use a bounded paired suite and reuse fixed cases; do not omit the perturbation axes that define the risk. | evaluation owner |
| A prompt instruction suppresses but does not measure bias. | high | high | Keep perturbation experiments and report deltas; prompt wording alone is not evidence of neutrality. | evaluation owner |
| Positive framing is confused with answer quality. | medium | high | Use content-only gold labels and neutral controls; keep sycophancy as a separate metric. | evaluation owner |
| Category projection is used as a validated IRT instrument too early. | medium | high | ADR 0005 rejects scalar/one-item input and this ADR blocks uncalibrated category claims. | maintainer |
| A large local model consumes device time or stalls before strict output. | medium | high | Use a bounded request timeout, record every timeout/parse failure, compare quality only on completed structured results, and keep a smaller verified fallback for exploratory work. | evaluation owner |

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
Connector API. It contains four accessible PDF attachments: Li et al. item
SHLVYKJC with attachment TVZMTEB8; Zheng et al. item GSZ4D83U with attachment
J44YVR37; Pezeshkpour and Hruschka item UFZQ8WN6 with attachment S5KQCN97; and Sharma et al. item
YDM7VXSG with attachment 47VH4PC7. The first, third, and fourth records expose
permissive OA terms used by the repository manifest; Zheng's PDF is retained
in Zotero for local research but its redistribution terms are not asserted.
Response-category records MYPNHHWJ and CWY355RP were also added for the
psychometric comparison. Jones--Loe is an OA SAGE Open record whose official
PDF endpoint returned anti-bot `403` locally. Iannario's publisher, Crossref,
OpenAlex, and local Zotero rights metadata identify the record as CC BY 4.0,
but its official PDF endpoint returned a WAF response and the Zotero item has
no child attachment. Cao et al. was added through the local Connector API as
item `393S5NXZ`; its record is all-rights-reserved, so its PDF was not copied.
None of these records is represented by a fabricated or regenerated PDF.

The Jones--Loe publisher page and PDF are marked open access and the original
is readable through the web research path, but the local download path still
returned 403. Iannario is licensed CC BY 4.0, but the local official download
returned a WAF response; license metadata alone does not prove that a fetched
byte stream is the publisher original or a valid Zotero parent attachment.
The four attached PDFs above remain the only attachments counted as verified
originals until an additional OA file passes a PDF magic header, size,
checksum, provenance, and Zotero attachment-parent check.

Revalidation on 2026-08-12 confirmed the four attachment records and their
local files: `TVZMTEB8`, `J44YVR37`, `S5KQCN97`, and `47VH4PC7` each have a
matching PDF file size and MD5 recorded by the Zotero Local API. The running
client reports `X-Zotero-Version: 9.0.6`, so its Local API is read-only and
cannot perform the write/file-upload phase needed for the Jones--Loe
attachment. Official Zotero documentation now describes local writes and file
uploads for Zotero 10+ with an authorized local API key; this installation is
not that write-capable path; `/api/local/authorize` is also absent and item
PATCH is unsupported. Direct retries against the official Iannario PDF URL
returned HTTP 202 with zero bytes, while the official Jones--Loe PDF URL
returned HTTP 403. The OA landing pages and canonical PDF URLs remain
recorded below; web-crawler text, an HTML error page, a regenerated PDF, or an
unauthorised mirror must not be counted as the original. The Goal therefore
remains open for both publisher-original attachments until a byte-verified
parent attachment or a documented, authorised retrieval route is available.

An Internet Archive capture of the canonical De Gruyter PDF was also
revalidated on 2026-08-12 as a 19-page PDF (1,074,249 bytes, MD5
`263d2effa1d7cc5bdc2748878e7f32d4`) captured from the publisher URL on
2024-04-13. It is historical retrieval evidence only: it is not a current
publisher endpoint, not a Zotero parent attachment, and its byte identity as
the requested publisher original was not independently established. It must
not be copied into the repository or counted as the requested OA original
until provenance and authorization are verified.

Primary sources:

* https://arxiv.org/abs/2506.22316
* https://proceedings.iclr.cc/paper_files/paper/2024/hash/54dd9e0cff6d9214e20d97eb2a3bae49-Abstract-Conference.html
* https://aclanthology.org/2024.findings-naacl.130/
* https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models
* https://www.degruyterbrill.com/document/doi/10.1515/ijb-2021-0013/html
* https://web.archive.org/web/20240413073305id_/https://www.degruyter.com/document/doi/10.1515/ijb-2021-0013/pdf
* https://journals.sagepub.com/doi/10.1177/2158244013489691
* https://journals.sagepub.com/doi/pdf/10.1177/2158244013489691
* https://www.iris.unina.it/handle/11588/877609
* https://www.zotero.org/support/dev/web_api/v3/local_api
* https://www.zotero.org/support/dev/web_api/v3/file_upload
