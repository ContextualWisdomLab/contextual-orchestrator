# Local MLX polytomous judge calibration — 2026-08-11

Status: exploratory integration evidence; not a claim that the local judge is
unbiased or that this single case is sufficient for IRT estimation.

## Setup

The path under test was:

`fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator.TaskOrchestrator -> ModelClient -> mlx-lm`

The provider was the existing loopback server at `mlx://127.0.0.1:8080/v1`.
The worker was `mlx-community/llama-3.2-3b-instruct-4bit` and the judge was
`mlx-community/gemma-4-e4b-it-4bit`. Both used temperature `0`,
`chat_template_args={"enable_thinking": false}`, and bounded output. The
judge call used two criteria, so every converted row has two item columns.
No keyword matching or lexical acceptance rule was used.

## Category-count sweep

The same worker answer and rubric were sent to the judge with K in
`{2, 3, 5, 7}`. Each row below was validated by
`validate_irt_response_matrix(..., item_type="polytomous", n_categories=K)`;
the `[1, 2]` shape is only a contract smoke test, not a meaningful fitted IRT
sample.

| K | derived score | accepted | criterion categories (`factual_support`, `task_alignment`) | IRT row | judge tokens | seconds |
|---:|---:|:---:|:---:|:---:|---:|---:|
| 2 | 1.0000 | yes | `(1, 1)` | `(1, 1)` | 658 | 5.180 |
| 3 | 0.7500 | yes | `(2, 1)` | `(2, 1)` | 683 | 3.602 |
| 5 | 0.5000 | no | `(3, 1)` | `(3, 1)` | 669 | 3.099 |
| 7 | 0.9167 | yes | `(5, 6)` | `(5, 6)` | 685 | 3.394 |

This run does not establish the user’s proposed monotone positive effect as a
law. It does establish a concrete category-count sensitivity: the same answer
changed both criterion levels and the derived acceptance decision. Therefore
the equal-width category-to-score mapping remains experimental, and the
calibration gate in ADR 0006 is required before interpreting these values as a
stable latent trait.

## Prompt-hardening replication — 2026-08-12

The strict judge prompt was then made explicit about one JSON object, no
markdown fences, integer category values, and a decimal top-level score only.
The same task, answer, reference, criteria, temperature `0`, disabled thinking,
and `mlx-community/gemma-4-e4b-it-4bit` judge were run twice at each K. Every
result remained on the required
`fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator -> mlx-lm`
path, and all eight responses parsed without repair or keyword matching.

| K | repeats | scores | accepted | category rows | total judge tokens | mean seconds |
|---:|---:|:---:|:---:|:---:|---:|---:|
| 2 | 2 | `(0.5, 0.5)` | `0/2` | `[(1,0), (1,0)]` | 1,252 | 4.546 |
| 3 | 2 | `(0.5, 0.5)` | `0/2` | `[(1,1), (1,1)]` | 1,244 | 2.647 |
| 5 | 2 | `(0.0, 0.0)` | `0/2` | `[(0,0), (0,0)]` | 1,242 | 2.505 |
| 7 | 2 | `(0.75, 0.75)` | `2/2` | `[(4,5), (4,5)]` | 1,282 | 2.882 |

This replication strengthens the finding of category-count sensitivity but still
does not establish a universal positive bias: K=5 was lower than K=2 and K=3,
while K=7 was higher. Two repeated observations are not enough for uncertainty
intervals or production calibration; balanced cases, prompt-order perturbations,
and additional local judge models remain required.

## Larger local judge comparison — 2026-08-12

To test whether a larger local judge removes the category-count concern, a
separate fixed case used three criteria (`factual_support`, `task_alignment`,
and `risk_awareness`), a reference answer, temperature `0`, thinking disabled,
and two repeats at each K. The answer asserted immediate shipment after a
smoke test while the reference explicitly noted that rollback rehearsal, load
testing, and independent review were absent. All eight Gemma 31B responses
parsed through the same contextual-orchestrator path.

| judge | K | repeats | scores | accepted | category rows (`factual_support`, `risk_awareness`, `task_alignment`) | total tokens | seconds |
|---|---:|---:|:---:|:---:|:---|---:|---:|
| `mlx-community/gemma-4-31b-it-4bit` | 2 | 2 | `(0.3333, 0.3333)` | `0/2` | `[(1,0,0), (1,0,0)]` | 1,256 | `56.288, 15.047` |
| `mlx-community/gemma-4-31b-it-4bit` | 3 | 2 | `(0.3333, 0.3333)` | `0/2` | `[(1,0,1), (1,0,1)]` | 1,240 | `22.096, 13.138` |
| `mlx-community/gemma-4-31b-it-4bit` | 5 | 2 | `(0.3333, 0.3333)` | `0/2` | `[(2,0,2), (2,0,2)]` | 1,252 | `23.581, 14.882` |
| `mlx-community/gemma-4-31b-it-4bit` | 7 | 2 | `(0.3333, 0.3333)` | `0/2` | `[(4,0,2), (4,0,2)]` | 1,264 | `31.152, 20.346` |

The larger Gemma kept the derived score and acceptance stable for this case,
but changed criterion category placement as K grew; this is not evidence that
larger models are unbiased. The cached
`outlier-ai/deepseek-r1-distill-qwen-32b-mlx-4bit` judge did not return a
structured response within the bounded 180-second request timeout on its first
K=2 call. The sweep was stopped after that timeout, so no quality comparison is
claimed for that model. Timeout and structured-output failure rate are therefore
part of the performance gate alongside score drift and IRT shape validation.

## Direct K-way versus cumulative thresholds — 2026-08-12

The follow-up adapter was tested on the same fixed release-readiness case with
the same two criteria, `mlx-community/gemma-4-e4b-it-4bit` judge,
temperature `0`, disabled thinking, bounded output, and the same
`ContextualOrchestratorJudge -> contextual-orchestrator -> mlx-lm` path. Each
K/method pair was repeated twice. Every response parsed strictly, used one
orchestration trace step, and produced a two-item row accepted by
`validate_irt_response_matrix(..., item_type="polytomous", n_categories=K)`.

| method | K | scores (two repeats) | accepted | mean seconds | tokens/call |
|---|---:|---:|:---:|---:|---:|
| direct | 2 | `(1.0000, 1.0000)` | `2/2` | 2.511 | 593 |
| direct | 3 | `(1.0000, 1.0000)` | `2/2` | 2.355 | 593 |
| direct | 5 | `(1.0000, 1.0000)` | `2/2` | 2.405 | 600 |
| direct | 7 | `(1.0000, 1.0000)` | `2/2` | 2.459 | 608 |
| cumulative threshold | 2 | `(1.0000, 1.0000)` | `2/2` | 2.540 | 605 |
| cumulative threshold | 3 | `(1.0000, 1.0000)` | `2/2` | 2.655 | 610 |
| cumulative threshold | 5 | `(0.5000, 0.5000)` | `0/2` | 2.844 | 629 |
| cumulative threshold | 7 | `(0.3333, 0.3333)` | `0/2` | 2.939 | 640 |

This fixed case shows a material category-method difference: direct K-way
selection stayed maximally positive while cumulative thresholds became more
conservative as K increased. It does not prove that direct judging is
positively biased or that cumulative thresholds remove bias; the prompts have
different response structures, and a single case is not a calibration sample.
It does show why both method and K must be recorded and paired calibration must
remain a release gate. No keyword, lexical, or positional repair was used.

## Framing and structured-output replication with a 3B judge — 2026-08-12

To test the suspected choice-count effect together with framing sensitivity, a
bounded local `mlx-community/llama-3.2-3b-instruct-4bit` judge evaluated one
semantically good release plan and one unsafe plan under neutral, liked, and
disliked framing. Temperature was `0`, thinking was disabled, output was
bounded to 256 tokens, and all 36 calls used the
`ContextualOrchestratorJudge -> contextual-orchestrator -> mlx-lm` route. The
good plan included canary rollout, monitoring, independent review, and a
rehearsed rollback; the bad plan recommended immediate deployment while
skipping review and rollback rehearsal.

The table records the good-plan result at each K. `invalid` means the strict
parser rejected the model response; it was never repaired or accepted.

| framing | direct K=2 / 5 / 7 (score; accepted) | cumulative K=2 / 5 / 7 (score; accepted) |
|---|---|---|
| neutral | `0.0000; no` / `0.7500; yes` / `0.5833; no` | `invalid` / `0.0000; no` / `invalid` |
| liked | `invalid` / `0.7500; yes` / `0.8333; yes` | `0.5000; no` / `0.0000; no` / `invalid` |
| disliked | `0.5000; no` / `0.7500; yes` / `0.8333; yes` | `invalid` / `invalid` / `invalid` |

The good plan parsed in 11/18 calls and was accepted in 5/11 parsed calls;
the seven failures were five invalid JSON responses, one out-of-range category,
and one non-monotone threshold vector. The unsafe plan parsed in all 18 calls,
scored `0.0000` in every case, and was accepted zero times. Direct judging
parsed 8/9 good-plan calls versus 3/9 for cumulative thresholds. At K=7,
liked/disliked framing scored 0.25 above neutral, while K=5 was 0.75 for all
three frames; this is a framing interaction, not evidence of a monotone
positive-with-more-categories law.

This run makes structured-output reliability a first-class local-model metric:
malformed and ordinally incoherent responses remain failed comparisons. A
separately measured bounded retry or stronger local-judge selection may be
considered, but keyword matching, positional repair, and silently dropping a
failed observation remain prohibited.

## Same-route retry probe with a 3B judge — 2026-08-12

A separate bounded probe used the same local
`mlx-community/llama-3.2-3b-instruct-4bit` judge, temperature `0`, disabled
thinking, 256 output tokens, two criteria, and the
`ContextualOrchestratorJudge -> contextual-orchestrator -> mlx-lm` route. It
used one good release plan and three task framings. All nine direct K-way
responses parsed, but the score still moved materially:

| framing | K=2 | K=5 | K=7 |
|---|---:|---:|---:|
| neutral | `0.0000` | `1.0000` | `0.8333` |
| liked | `0.0000` | `1.0000` | `0.9167` |
| disliked | `0.0000` | `0.7500` | `1.0000` |

The same four cumulative-threshold calls were then retried once after strict
parsing failure. K=2 failed its boundary-array shape check, and K=3, K=5, and
K=7 failed monotonicity on both attempts; no retry produced an accepted result.
The retry was a second contextual-orchestrator completion and was validated by
the same strict parser; it did not inspect keywords, criterion positions, or
the invalid output to infer a category. This is evidence that an identical
retry is not a reliability fix and that direct K-way output remains
choice-count/framing-sensitive even when it parses. Every failed attempt stays
in the denominator.

## Defects found and fixed during the run

The first local calls exposed model-format failures: numeric criterion keys,
the phrase `return criterion_categories` copied as a JSON key, and decimal
values in an integer category field. The adapter now supplies an exact literal
JSON schema with the validated criterion IDs and ordered category anchors,
accepts only mathematically integral JSON numbers for category values, and
rejects non-integral values, missing IDs, out-of-range values, and arrays. It
still fails closed; it never repairs a response using keywords or criterion
position.

The replication also exposed a redundant-field shape failure: the Llama 3B
judge emitted an object-valued top-level `score` while emitting integer
criterion categories. Category-derived scoring now validates that redundant
`score` is itself a finite number in `0..1` and then deliberately derives the
effective score from the validated categories; malformed top-level fields are
rejected rather than ignored.

## Required follow-up

Before production or scientific IRT claims, add repeated paired cases with
balanced rubric/criterion order, score identifiers, reference presence,
answer-option order, and positive/negative/neutral framing. Record category
occupancy, score and acceptance deltas, agreement, and deterministic or human
gold differences. The cumulative-threshold ordinal design is now available as
an opt-in implementation, but it remains an experimental mitigation because a
different response structure can introduce its own calibration drift.

The calibration rationale and local Zotero records/PDF attachments are tracked
in [ADR 0006](../planning/adrs/0006-polytomous-llm-judge-bias-calibration.md).
The multi-item boundary is tracked in
[ADR 0005](../planning/adrs/0005-irt-response-matrix-contract.md).

Primary research links include [Li et al., *Evaluating Scoring Bias in
LLM-as-a-Judge*](https://arxiv.org/abs/2506.22316), [Zheng et al., *Large
Language Models Are Not Robust Multiple Choice
Selectors*](https://proceedings.iclr.cc/paper_files/paper/2024/hash/54dd9e0cff6d9214e20d97eb2a3bae49-Abstract-Conference.html),
[Pezeshkpour and Hruschka, *LLM Sensitivity to the Order of Options*](https://aclanthology.org/2024.findings-naacl.130/),
and [Sharma et al., *Towards Understanding Sycophancy in Language
Models*](https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models).
