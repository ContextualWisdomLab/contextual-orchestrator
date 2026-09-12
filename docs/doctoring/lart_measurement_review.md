# LaRT measurement review — 2026-09-12

Status: research intake; no implementation or production adoption.
Integration baseline: `be60791ba85cf9cfa8075b13646fa94b0d8a1031` (PR #1107
retained research branch). This note does not establish protected-main delivery.

## Primary evidence and read scope

Xu, Z., Liu, J., Wang, Y., & Gu, Y. (2026). *Latency-response theory model:
Evaluating large language models via response accuracy and chain-of-thought
length* (Version 4) [Preprint]. arXiv. https://arxiv.org/abs/2512.07019v4

Root inspected the abstract, introduction and relevant passages of §§5.1 and
7; independent agent review covered §§3–5 and 7. Neither is a replication or
complete appendix audit. The listed arXiv non-exclusive license does not
establish redistribution permission; no PDF is attached.

Section 7 defines length as reasoning tokens before the answer, counted with
each model's tokenizer, capped at 10,240. All-wrong models are excluded.
Sections 7.2.2 and 7.2.4 compare subset estimates with full-data fitted
estimates, not known true parameters. Section 5.1 requires informative
loadings for both traits and sign-orientation constraints. These findings do
not establish wall-clock latency reduction or causal benefit from more tokens.
Primary passages: https://arxiv.org/html/2512.07019v4#S7 and
https://arxiv.org/html/2512.07019v4#S5.SS1.

## Proposed experiment, not a paper result

Keep estimation in fast-mlsirm and consume its released contract in CO.
First agree an observation contract carrying tokenizer/version, prompt
condition, model family, truncation and missingness. Do not copy an estimator
into the gateway or introduce an uncalibrated token-length routing weight.

Compare accuracy-only and joint calibration on held-out model families and
items at equal evaluation budgets. Preserve failed outcomes in the target
denominator; report exclusion sensitivity separately. Use observed correctness
and calibration error for real responses. Known-parameter RMSE belongs to
unit recovery checks, not fitted-reference agreement on real data.

Before implementation, audit joint versus marginal uncertainty and the claimed
optimization conditions. For a positive-definite precision matrix
`[[A, C], [C, B]]`, marginal ability precision is `A - C*C/B`; substituting
`A` requires justification. This is an analytical review question, not a
confirmed defect in the paper or its implementation.

Measure CO decision-only milliseconds independently under the existing KPI
contract. No length proxy, subset stability statistic or test pass count may
replace that measurement. No production default changes are authorized by
this intake. Remaining gates: complete method audit, owner contract, licensed
data provenance, held-out evaluation and uncertainty verification.
