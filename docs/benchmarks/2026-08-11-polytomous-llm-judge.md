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

## Defects found and fixed during the run

The first local calls exposed model-format failures: numeric criterion keys,
the phrase `return criterion_categories` copied as a JSON key, and decimal
values in an integer category field. The adapter now supplies an exact literal
JSON schema with the validated criterion IDs and ordered category anchors,
accepts only mathematically integral JSON numbers for category values, and
rejects non-integral values, missing IDs, out-of-range values, and arrays. It
still fails closed; it never repairs a response using keywords or criterion
position.

## Required follow-up

Before production or scientific IRT claims, add repeated paired cases with
balanced rubric/criterion order, score identifiers, reference presence,
answer-option order, and positive/negative/neutral framing. Record category
occupancy, score and acceptance deltas, agreement, and deterministic or human
gold differences. The cumulative-threshold ordinal design remains the next
implementation direction because a single K-way choice can retain score-ID and
category-count bias.

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
