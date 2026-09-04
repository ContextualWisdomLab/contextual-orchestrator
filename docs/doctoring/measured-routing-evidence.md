---
title: "Measured routing evidence: latency ledgers, semantic affinity, triage, real-time judging"
status: "implemented"
date: "2026-08-25"
scope: "PR (stacked on #834), ADR 0034"
---

# Measured routing evidence

## Decision

ADR 0034 removes every task-keyword heuristic from the routing path and
replaces it with an evidence ladder: operator-declared eligibility, exact
tag/priority/cosine ordering, and measured member behavior inside model
groups. Two measurement systems feed the ladder:

- **Transport ledger** — Beta(1,1)-posterior success stability divided by
  EWMA latency, using Jacobson's (1988) 1/8 gain and a floor at
  `MIN_ROUTING_LATENCY_SECONDS` so division never amplifies noise.
- **Quality ledger** — the same Beta-Bernoulli arithmetic fed by the
  real-time fast-mlsirm judge on direct-route answers, so judged
  acceptability (not just transport success) steers intra-group order.

The ranking quantity `stability / ewma_latency_seconds` has the unit expected
successful responses per second across every member. Token throughput remains
diagnostic evidence and is not mixed into that score. Workflow triage is a strict structured call that
fails closed to conducted orchestration when its reply violates the exact
`{"workflow_required": bool}` schema.

## Research-to-code mapping

| Implementation boundary | Evidence-informed reason | Acceptance evidence |
| --- | --- | --- |
| EWMA with gain 1/8 for latency and throughput | Jacobson's congestion-avoidance estimator is the canonical low-pass filter for volatile network measurements; it needs no tuning window. | Exact-arithmetic tests reproduce hand-computed EWMA values. |
| Laplace rule of succession as stability prior | The uniform Beta(1,1) posterior mean is the minimum-assumption estimate of a Bernoulli accept probability (Gelman et al., 2013). | Stability tests assert alpha/(alpha+beta) exactly. |
| Cosine similarity over declared metadata documents | Dense retrieval established query-document cosine ordering without keyword overlap (Karpukhin et al., 2020). Affinity uses operator-declared descriptors only. | Deterministic mock-embedding tests verify cosine ordering and zero-vector guards. |
| Strict JSON triage verdict | LLM judges are reliable only under constrained output schemas; Zheng et al. (2023) show judge agreement collapses without structure. Fail-closed preserves verification guarantees. | Parser tests reject seven malformed-reply classes and cache verdicts by content hash. |
| Real-time judging before returning answers | RouteLLM/FrugalGPT motivate quality-aware routing between models (Ong et al., 2024; Chen et al., 2023); here quality is measured per deployment instead of trained offline. | Judge-driven failover tests prove rejection routes to the next candidate within budget while updating both ledgers. |
| Multi-layer simple-structure measurement (fast-mlsirm) | Judged quality is modeled per member rather than pooled, avoiding atomistic fallacy across heterogeneous providers (Jeon et al., 2021). | Quality-ledger reports expose per-member posteriors consumed by `_measured_member_order`. |
| Language/domain validity boundary | IRT-Router treats LLMs as persons and queries as items, so query language cannot be inserted as a person-group DIF label. Multilingual-IRT instead models language difficulty deviations and separates language from content discrimination (Lior et al., 2026). | The synthetic report keeps `measurement_validity=false`; no language or domain label can open the production gate without a released item-side owner contract and buyer replication. |

## Accuracy and decision-latency KPI

Run
`uv run --python 3.12 python scripts/benchmark_psychometric_routing.py`.
Python 3.12 is explicit because the locked NumPy/fast-mlsirm benchmark
dependencies are intentionally unavailable on the product's supported Python
3.10 and 3.11 runtimes. The benchmark
fixes the native fit and probability output, then measures only gateway matrix
preparation and ranking for 512 contexts, four models, and two dichotomous
items per context. Lower median milliseconds is better; the psychometric and
reasoning-effort tests must remain green.

Protected `main@2e414d15` measured 2.448167 ms. Candidate performance commit
`0561c9b81f68bd9be9bd413f4a23892717e54701`, carried by PR #1058, measured 1.100583 ms, a
55.04% reduction. This local same-host result does not prove production
latency or answer accuracy. The next accuracy experiment must use a held-out
model-query matrix and report log loss or Brier score alongside routing regret;
true-parameter simulations must continue to report RMSE.

The successor observation-path experiment uses the same 512-context ledger.
Replacing one model/context row fell from p50 0.133833 ms and p95 0.152166 ms
on `b2f90116` to p50 0.000875 ms and p95 0.001000 ms. The benchmark now emits
both fields. This is local gateway bookkeeping evidence; the fit, held-out
quality, and provider latency remain separate KPIs.

Run `uv run python scripts/benchmark_psychometric_heldout.py` for the separate,
explicitly enabled semantic warm-start experiment. Production retains the
validated single-neighbor behavior. On its fixed 24-training/24-held-out smooth
latent-response surface, the single-neighbor baseline at `0ae0ed8c` reports
Brier 0.1438369123, log loss 0.4525311878, mean top-choice regret 0.0024259478,
and decision p50 about 0.0212 ms. Two-neighbor positive-cosine interpolation at
`50d91c9e`, carried by PR #1061, reports Brier 0.1418346845, log loss
0.4475784303, zero top-choice regret, and p50 near 0.02 ms. Source commit
`94615dff` adds paired, seeded 2,000-resample bootstrap intervals and 200 timing
repetitions per held-out context, alternating execution order to reduce warmup
and drift bias. A same-host run reports candidate-minus-baseline Brier `[-0.0022969, -0.0016986]`,
log loss `[-0.0053736, -0.0045191]`, and regret `[-0.0072778, 0]`; candidate
p50 was 0.0386 ms versus baseline 0.0340 ms, with paired context-median latency
delta `[0.0047666, 0.0054775]` ms. This seeded simulation isolates
unseen-context interpolation; it is not a substitute for preregistered buyer
prompts, observed judge outcomes, or end-to-end latency. The experimental result
cannot alter live routing while the latency and buyer-validity gates remain open.
Report-contract commit `2cc8427f` emits each candidate-minus-baseline point
delta beside its interval and tests that the metric sets match and every point
lies inside its reported interval.
Fail-closed gate commit `079b3f80` separately reports accuracy non-inferiority,
decision-latency improvement, buyer-heldout status, and measurement validity.
This synthetic run passes only accuracy; therefore
`production_default_change_allowed` is false.
Production-path source commit `70cfc91f` restores one-pass `max()` selection for
the single-neighbor default while retaining full top-2 ordering only inside the
experiment. A same-process 512-row `timeit` comparison measured 5.5 µs for
`max()` versus 27 µs for `sorted(..., reverse=True)[:1]`; this isolates neighbor
selection and is not an end-to-end route-latency claim.
Experimental source commit `972bd4a0` reads the two selected score maps once
per candidate rather than rebuilding filtered numerator and denominator
generators. Ten whole-process pairs alternated baseline/candidate order. The
median candidate decision p50 fell from `0.0180415` to `0.016708` ms (7.39%);
the paired context-median latency-delta CI upper bound fell from `0.0022899` to
`0.0006677` ms (70.84%). Brier `0.1418346845`, log loss `0.4475784303`, and
regret `0` were identical in every pair. Because the CI upper bound remains
positive, this improvement does not open the latency or production gate.

## APA 7 references

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*. arXiv.
https://arxiv.org/abs/2305.05176

Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., &
Rubin, D. B. (2013). *Bayesian data analysis* (3rd ed.). CRC Press.

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM
Computer Communication Review, 18*(4), 314–329.
https://doi.org/10.1145/52325.52356

Jeon, M., Jin, I. H., Schweinberger, M., & Baugh, S. (2021). Estimating
parameters for unidimensional multidimensional logistic item response
models. *Psychometrika*. https://doi.org/10.1007/s11336-021-09783-y

Nadaraya, E. A. (1964). On estimating regression. *Theory of Probability &
Its Applications, 9*(1), 141–142. https://doi.org/10.1137/1109020

He, Y., & Qi, Y. (2023). Using response time in multidimensional computerized
adaptive testing. *Journal of Educational Measurement, 60*(4), 697–738.
https://doi.org/10.1111/jedm.12373

Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D.,
& Yih, W.-t. (2020). Dense passage retrieval for open-domain question
answering. In *Proceedings of the 2020 Conference on Empirical Methods in
Natural Language Processing* (pp. 6769–6781). Association for
Computational Linguistics. https://doi.org/10.18653/v1/2020.emnlp-main.550

Laplace, P.-S. (1774). Mémoire sur la probabilité des causes par les
événements. *Mémoires de l'Académie Royale des Sciences de Paris, 6*,
621–656. (Rule of succession; modern treatment in Gelman et al., 2013.)

Lior, G., Frostig, T., Stanovsky, G., & Eyal, M. (2026). *Extending item
response theory for efficient and meaningful multilingual evaluation*
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2606.15643

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs
with preference data*. arXiv. https://arxiv.org/abs/2406.18665

Song, W., Huang, Z., Cheng, C., Gao, W., Xu, B., Zhao, G., Wang, F., & Wu, R.
(2025). *IRT-Router: Effective and interpretable multi-LLM routing via item
response theory* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2506.01048

Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., Lin,
Z., Li, Z., Li, D., Xing, E., Zhang, H., Gonzalez, J. E., & Stoica, I.
(2023). *Judging LLM-as-a-judge with MT-Bench and Chatbot Arena*. arXiv.
https://arxiv.org/abs/2306.05685
