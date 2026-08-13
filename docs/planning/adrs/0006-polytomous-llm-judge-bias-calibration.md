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

For high-stakes polytomous use, the fast adapter now provides an opt-in
`category_method="cumulative_threshold"` mode with an explicit `category_count`.
It asks the model whether each criterion clears each ordered boundary, validates
that the Boolean boundary vector is monotone, and derives the category from the
number of cleared thresholds. This reduces dependence on one K-way score-ID
choice, but it does not make the judge unbiased: the same answer must still be
calibrated across K, prompt perturbations, models, and gold labels.

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
| A cumulative-threshold prompt can still produce inconsistent or non-monotone boundary judgments, and its score can differ from direct K-way output. | Reject non-Boolean, wrong-length, or false-then-true vectors; record category method, K, trace, usage, parse success, score, acceptance, and perturbation deltas in every benchmark. | Implemented in adapter/tests; calibration ongoing |
| Multiple criteria can still be correlated or cover one latent dimension poorly. | Require item coverage review, factor anchors, and sample-size checks before interpreting IRT fit. | Required next |
| A single judge call can hide model drift. | Preserve contextual-orchestrator trace, model identity, prompt variant, category count, and usage in benchmark records. | Implemented in adapter trace and the 2026-08-11 benchmark artifact |
| A one-person, two-item matrix can pass a shape check while remaining insufficient for IRT estimation. | Require multiple persons, item-information, and factor-coverage checks before fitting or interpreting an IRT model. | Required next |
| A larger local judge can preserve the aggregate score while moving criterion categories, and a cached 32B judge timed out before producing structured output. | Gate model comparisons on bounded latency, timeout rate, strict-parse success, token usage, category occupancy, and score/acceptance drift; never treat a timeout as a missing or positive result. | Implemented in the 2026-08-12 benchmark; reliability calibration ongoing |
| A cached local 3B judge failed to emit valid or ordinally coherent structured output in 7/18 good-plan calls, and framing changed some K=7 scores. | Keep every malformed/monotonicity failure in the denominator; compare a separately measured bounded retry or stronger local judge only through contextual-orchestrator, and never add keyword, positional, or silent-drop repair. | Recorded in the 2026-08-12 benchmark; reliability/framing calibration required |
| An identical second contextual-orchestrator completion recovered none of four cumulative-threshold failures in a follow-up 3B probe, while direct K-way scores shifted across K and framing. | Keep blind retry out of the production contract. If recovery is pursued, compare a bounded independent binary-threshold decomposition or stronger local judge on held-out paired cases, record added latency/tokens and first/final parse status, and preserve strict fail-closed parsing. | Measured 2026-08-12; Goal expanded and calibration required |
| A live bearer-authenticated gateway probe on the same Llama 3B answer and two criteria at `K=5` produced direct `1.0000` (`4/4`, accepted) versus cumulative-threshold `0.0000` (`0/0`, rejected), with both strict parses valid and one contextual-orchestrator trace step each. | Treat this as paired method sensitivity, not as a positive-bias conclusion. Keep method/K/trace/usage in the denominator, compare balanced held-out cases, and retain the multi-item polytomous validator; never repair the disagreement lexically or positionally. | New evidence 2026-08-12; calibration required |
| OA metadata does not guarantee that the original PDF can be downloaded into the local Zotero library: Zotero 9 exposes read-only Local API reads and SAGE returned anti-bot `403` for the Jones--Loe PDF. The Iannario publisher/aggregator record currently reports full-text restriction, so it is citation-only rather than an outstanding OA-PDF obligation. | Record the official landing/PDF URL and retrieval evidence, attach only byte-verified original PDFs through the local Connector/API, and retry the Jones--Loe OA source from an authorized route or a Zotero version with local write/file-upload support. Never regenerate, OCR-rebuild, or substitute a PDF while claiming it is the original. | Required follow-up |

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
PDF endpoint returned anti-bot `403` locally; Iannario's publisher/aggregator
record reports full-text restriction. Neither is represented by a fabricated
or regenerated PDF.

The Jones--Loe publisher page and PDF are marked open access and the original
is readable through the web research path, but the local download path still
returned 403. The Iannario publisher/aggregator record reports restricted
full-text access; a public metadata page or an archive capture is not a
redistribution license. The four attached PDFs above remain the only
attachments counted as verified originals until an additional OA file passes
a PDF magic header, size, checksum, and Zotero attachment-parent check.

Revalidation on 2026-08-12 confirmed the four attachment records and their
local files: `TVZMTEB8`, `J44YVR37`, `S5KQCN97`, and `47VH4PC7` each have a
matching PDF file size and MD5 recorded by the Zotero Local API. The running
client reports `X-Zotero-Version: 9.0.6`, so its Local API is read-only and
cannot perform the write/file-upload phase needed for the Jones--Loe
attachment. Official Zotero documentation now describes local writes and file
uploads for Zotero 10+ with an authorized local API key; this installation is
not that write-capable path. Direct retries against the official Iannario PDF
URL returned HTTP 202 with zero bytes, while the official Jones--Loe PDF URL
returned HTTP 403. The OA landing pages and canonical PDF URLs remain
recorded below; web-crawler text, an HTML error page, a regenerated PDF, or an
unauthorised mirror must not be counted as the original. The Goal therefore
remains open for the Jones--Loe original until a byte-verified parent
attachment or a documented, authorised retrieval route is available.

An Internet Archive capture of the canonical De Gruyter PDF was also
revalidated on 2026-08-12 as a 19-page PDF (1,074,249 bytes, MD5
`263d2effa1d7cc5bdc2748878e7f32d4`) captured from the publisher URL on
2024-04-13. It is historical retrieval evidence only: it is not a current
publisher endpoint, not a Zotero parent attachment, and not a redistribution
license. It must not be counted as the requested OA original or copied into
the repository until an authorized route establishes those rights.

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
