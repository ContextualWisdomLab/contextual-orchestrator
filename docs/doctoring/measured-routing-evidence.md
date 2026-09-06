---
title: "Measured routing evidence: diagnostics versus identified decision authority"
status: "superseded-as-routing-policy"
date: "2026-09-01"
scope: "ADR 0034; PR #1000"
---

# Measured routing evidence

## Current decision

This record supersedes the earlier 2026-08-25 claim that transport and quality
measurements formed a valid routing ladder. The repository still measures useful
quantities such as provider success/failure observations, latency, throughput,
price vectors, and fast-mlsirm response-quality evidence, but a quantity being
measured or mathematically defined does **not** by itself identify a valid
model-selection estimand.

The earlier policy combined a Beta-Bernoulli posterior with EWMA latency as
`P(success) / latency`, used static priority/cosine metadata ordering, and could
fall back to identifier or declaration order. Those operations are reproducible,
but the cited literature does not establish that this particular quotient,
metadata cosine, priority value, or identifier ordering estimates the product's
required routing outcome. They therefore no longer have decision authority.

PR #1000 makes these boundaries fail closed:

- transport and quality ledgers remain separately observable diagnostics;
- `ModelGroupRouter.member_score`, private composite-scoring seams, and
  multi-member measured ordering cannot choose a model;
- multiple eligible agents require a unique exact-context fast-mlsirm fit or an
  explicit eligible model/agent selection; equal fitted probabilities remain
  unresolved rather than using an identifier or input-order tie-break;
- an unseen prompt cannot borrow the nearest observed prompt's psychometric
  score through cosine similarity;
- sync versus batch is selected only by explicit caller channel (subject to the
  operator batch kill switch), not latency-tolerant/priority/token thresholds;
- local semantic embeddings require an explicit embedding implementation;
  the SHA-derived pseudo-embedding is a fail-closed compatibility tombstone;
- cost comparison requires the exact request token shape and a unique minimum;
  equal costs remain unresolved;
- NIM benchmark budget/cost evidence uses complete provider-reported token
  usage. Character-count token estimation is prohibited. When the request mix
  is unknown, a cheapest NIM worker exists only if one complete price vector is
  component-wise no more expensive than every competitor and strictly cheaper
  in at least one component; equal/crossing/incomplete vectors remain
  unresolved.

## Research-to-code mapping

| Evidence or algorithm | What the literature supports | Current authority |
| --- | --- | --- |
| Beta-Bernoulli success observations | A probabilistic summary of observed Bernoulli outcomes when the model assumptions apply. | Diagnostic only. No hand-composed transform of this posterior selects a route. |
| EWMA latency/throughput | A smoothing estimator for observed transport quantities. | Diagnostic only. No fixed gain or posterior/latency quotient is model-selection authority. |
| Dense-vector cosine similarity | Similarity for a retrieval estimand when embeddings are semantically trained for that task. | Not an LLM-quality generalization rule. No nearest-context psychometric transfer. |
| fast-mlsirm MLSRM/IRT evidence | Explicit psychometric estimation from governed response observations. | May order candidates only for the exact observed canonical prompt context when the fitted model converges and yields a unique complete ordering. Otherwise fail closed. |
| RouteLLM | Learned routing from preference data. | Research basis for trained/evaluated routing, not for static priority or threshold substitutes. |
| FrugalGPT | Learned/evaluated cascades under quality/cost objectives. | Research basis for evaluated cascades, not arbitrary fallback order. |
| Conductor / TRINITY / Sakana Fugu | Learned or searched orchestration policies with explicit optimization/evaluation procedures. | Research basis for trained/evaluated orchestration; hand-authored proxy scores do not inherit their validity. |
| Provider token `usage` and published price vectors | Direct accounting evidence for the executed request/model where the provider reports complete usage and pricing metadata is valid. | Authoritative for benchmark accounting/cost only; missing evidence fails closed rather than being estimated from characters or an assumed request mix. |

## Exact-head evidence

The PR #1000 source-repair workflow first executed the no-heuristic NIM
regressions against the pre-repair exact head and observed all four intended RED
failures: character-token estimation did not fail closed, missing provider usage
was accepted, reported usage was not retained as the accounting authority, and
equal price vectors were broken by the historical selector. It then applied the
production repair and ran the focused NIM benchmark suites: **102 tests passed**
on the repaired worktree, followed by a clean `git diff --check`. The workflow
created commit `6263def7b74ed7a00a4aece07a94d47095568961` and removed its temporary
source-fix workflow, trigger, and repair drivers before pushing the branch.
Hosted PR checks and independent review on the resulting exact head remain the
merge authority.

The dry-run benchmark intentionally reports no Pareto frontier and no paired
comparison when every candidate policy fails closed for missing exact-context
routing evidence. Creating comparisons from such cells would manufacture
statistical evidence rather than preserve the observed unresolved state.

## APA 7 references

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., & Rubin,
D. B. (2013). *Bayesian data analysis* (3rd ed.). CRC Press.

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM Computer
Communication Review, 18*(4), 314–329. https://doi.org/10.1145/52325.52356

Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D., &
Yih, W.-t. (2020). Dense passage retrieval for open-domain question answering.
In *Proceedings of the 2020 Conference on Empirical Methods in Natural Language
Processing* (pp. 6769–6781). Association for Computational Linguistics.
https://doi.org/10.18653/v1/2020.emnlp-main.550

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2406.18665

Sakana AI. (2026, April 24). *Sakana Fugu: A multi-agent orchestration system as
a foundation model*. https://sakana.ai/fugu-beta/

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*TRINITY: An evolved LLM coordinator* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04695
