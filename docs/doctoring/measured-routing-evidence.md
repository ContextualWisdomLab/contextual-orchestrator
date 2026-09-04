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
| Probability calibration | Cox (1958) motivates logistic recalibration; Arrieta-Ibarra et al. (2022) distinguish calibration diagnostics from aggregate probabilistic scores. | Source `92b9309b` moves held-out calibration slope from `0.991445` to `1.014030` and reduces logit RMSE from `0.231235` to `0.025803`; the paired improvement interval is `[-0.208030, -0.202924]`. Synthetic truth does not replace buyer outcome calibration. |
| Real-time judging before returning answers | RouteLLM/FrugalGPT motivate quality-aware routing between models (Ong et al., 2024; Chen et al., 2023); here quality is measured per deployment instead of trained offline. | Judge-driven failover tests prove rejection routes to the next candidate within budget while updating both ledgers. |
| Multi-layer simple-structure measurement (fast-mlsirm) | Judged quality is modeled per member rather than pooled, avoiding atomistic fallacy across heterogeneous providers (Jeon et al., 2021). | Quality-ledger reports expose per-member posteriors consumed by `_measured_member_order`. |
| Language/domain validity boundary | IRT-Router treats LLMs as persons and queries as items, so query language cannot be inserted as a person-group DIF label. A released explanatory-IRT covariate supports one item-side difficulty contrast (Debeer & Janssen, 2013); Multilingual-IRT additionally separates language from content discrimination (Lior et al., 2026). | Source `0f875e3f` converges after 941 iterations and estimates `-0.789650` for a known `-0.8` contrast. The synthetic report still keeps `measurement_validity=false`; preregistered covariates, anchors, and linked buyer observations remain required, while language-specific discrimination and residual effects remain unavailable. |
| Parameter uncertainty boundary | Oakes (1999) derives observed information for EM fits; Pritikin (2017) compares covariance estimators for item-factor models. | Source `b0f3703f` reuses the released Oakes API: six known intercepts have RMSE `0.039160`, 95% interval coverage `1.0`, and mean width `0.295945`. Buyer calibration remains required, and the current API conditions on population parameters and rejects anchors, zero inflation, and item covariates. |
| Recalibration invariance boundary | Millsap (2010) requires longitudinal invariance before changes in the latent construct are interpreted; Babcock and Albano (2012) show common-item drift can damage linked classifications. | Source `2e129e2a` links through seven stable anchors and flags the one injected drift item with no stable-item false positive. The fixed `0.25` tolerance is an effect-size screen only; buyer recalibrations, sampling uncertainty, and review rules remain required. |
| Candidate-roster invariance boundary | Tinsley and Dawis (1975) connect sample-free calibration to adequate sampling, unbiased design, and model fit. | Source `5c6ba17a` separately fits 20- and 16-candidate synthetic rosters and links 200 common items. Linked common-score RMSE is `0.010866`, correlation is `0.999999`, and maximum shift is `0.016498`; versioned buyer rosters and registered shift targets remain required. |
| Functional drift impact | Guo, Zheng, and Chang (2015) evaluate drift by its effect on the test characteristic curve rather than isolated parameter distance. | Source `c7c4a13f` detects the one injected function-changing item and reduces TCC-area difference from `0.123355` to zero. The released backward-only fixed-threshold heuristic is not the paper's full stepwise method; buyer recalibrations and preregistered review rules remain required. |
| Sequential drift delay | Chen, Lee, and Li (2022) frame item drift monitoring as sequential change detection with compound false- and missed-detection risk. | Source `1b3b7244` searches 11 thresholds on 500 calibration runs using a 95% Wilson false-alarm bound, then evaluates threshold `6.6` on an independent 500-run seed. Held-out false alarms are `2.4%` with upper bound `4.15%`; delay p50 is 10 and p95 is 20 observations. Buyer time series, risk weights, and preregistered targets remain required. |
| Alternate-form score equating | AERA, APA, and NCME (2014, Standards 5.16–5.18) require evidence for comparable score meaning across alternate item sets; Moses and Holland (2008) provide an observed-score equating framework with uncertainty. | Source `1dce9688` recovers known slope `2` and intercept `1`, reducing raw cross-form RMSE from `6.782330` to zero. Three hundred bootstrap 95% intervals cover all 11 known equivalent scores; buyer forms, comparable populations or anchors, and error targets remain required. |
| Candidate response-pattern fit | Meijer (1996) and Tendeiro et al. (2016) treat person fit as a screen for response vectors that depart from a model or comparison group. With LLM deployments in the person role, this becomes a candidate-pattern review signal. | Source `a18e25f7` ranks one injected inverted pattern first among 1,000 candidates, with ZU3 separation `1.818719` from the next-highest pattern. It does not infer a cause or apply a universal cutoff; complete buyer candidate-by-criterion responses and a review policy remain required. |
| Construct dimensionality screen | Horn (1965) compares observed roots with random-data roots; Tran and Formann (2009) show that parallel analysis, especially with Pearson correlations, is unreliable as proof of unidimensionality for binary items. | Source `73e07a8e` recovers the two known dimensions in a seeded 1,000-response, 12-item simulation. This is an implementation screen only; buyer responses, a preregistered construct structure, and confirmatory holdout fit remain required. |
| Global model-fit screen | Maydeu-Olivares and Joe (2005) derive limited-information goodness-of-fit tests for binary contingency tables; Xu et al. (2017) show that M2 sensitivity depends on the multidimensional structure. | Source `7f13dc7d` accepts a fitted one-factor synthetic case at `p=0.105619` and detects known two-factor misspecification at `p≈2.27e-41`. Complete buyer responses, a preregistered model, and held-out fit review remain required. |
| Score reliability | Bechger et al. (2003) connect IRT posterior uncertainty with classical reliability; Stanley and Edwards (2016) show that reliability and model fit answer different questions. | Source `5b50e10c` raises empirical reliability from `0.366437` to `0.800436` when known discrimination rises from `0.45` to `1.5`. Buyer calibration, posterior errors, a purpose-specific target, and separate fit evidence remain required. |
| Cross-condition generalizability | Huebner and Lucht (2019) separate person, item, occasion, and interaction variance and use D-studies to evaluate alternate evidence designs. | Source `015c4bf6` decomposes an 80-candidate, 12-query, four-occasion synthetic tensor. Dependability rises from `0.401565` at one query and one occasion to `0.849616` at 12 and four; complete balanced buyer observations, random-facet justification, and a registered target remain required. |
| Conditional information | Lord (1950) requires precision to be evaluated at the ability level where a decision is made; Magis (2013) grounds the item-information calculation. | Source `b4efa489` improves worst information across trait points `[-2, 0, 2]` by `15.789%` when 12 item difficulties cover `[-2, 2]`, reducing worst conditional standard error from `0.890897` to `0.827931`. Buyer-relevant regions and calibrated buyer items remain required. |
| Classification decision error | Rudner (2001, 2005) evaluates classification accuracy and consistency from the score-error distribution around an explicit cut. | Source `0b19116e` reduces synthetic standard error from `0.8` to `0.2`, raising expected accuracy from `0.814182` to `0.996895` and consistency from `0.710275` to `0.993829`. Buyer cuts, linked measures, decision costs, and preregistered targets remain required. |
| Decision utility boundary | Taylor and Russell (1939) connect validity, selection ratio, and base rate to expected selection outcomes; the Brogden-Cronbach-Gleser model subtracts measurement cost from valued outcome gain. | Source `452a3649` raises synthetic validity from `0.2` to `0.6`, increasing selected success from `0.500273` to `0.723515` and net utility from `2,042.21` to `5,626.64`; holding validity fixed while raising total cost to `10,000` changes net utility to `-2,373.36`. This personnel-selection model is an analogue, not validated routing economics; buyer outcome units, costs, volume, and targets remain required. |
| Predictive-fit axes | Stenhaug and Domingue (2022) distinguish missing-response prediction for observed persons from complete-response prediction for new persons. | Source `68831dff` labels the existing synthetic held-out-query Brier and log-loss evidence as the known-candidate task. Source `54833bd8` executes the unseen-candidate path across 24 contexts and measures zero psychometric prediction coverage. Versioned buyer outcomes for both axes remain required. |
| Adaptive candidate onboarding | Bock and Mislevy (1982) ground adaptive EAP scoring; Hau and Chang (2001) evaluate maximum-information selection at early CAT stages. | Source `f4513527` reuses the released Rust-backed path across 400 known synthetic candidates. Maximum-information selection reaches SE 0.5 in 7.1775 queries on average versus 10.47 for random order. Paired 95% intervals are `[-3.4125, -3.18]` queries, `[-0.080874, 0.006129]` theta squared error, and `[-0.008804, -0.005716]` unobserved-probability squared error. The theta interval includes zero. It measures calibration-query burden, not live decision latency, buyer validity, or invariant ability. |
| Classification-oriented stopping and rejection | Luo, Kim, and Dickison (2018) describe CI stopping around an explicit decision cut and its near-cut inefficiency; Chow (1970) and El-Yaniv and Wiener (2010) frame abstention as an error–coverage tradeoff. | Source `f4cceb59` stops when a 95% normal interval excludes cut zero or after 12 queries. Across 400 known synthetic candidates it averages 9.875 queries, stops early for 41%, and exactly matches the fixed-length decisions and 0.9125 accuracy. Source `298e1fc8` exposes near-cut accuracy of 0.70. Source `e1ff2e61` chooses `z=1.645` on a development seed under a 2.5% Wilson error-upper-bound rule. On one paired holdout it raises coverage from 44.25% to 56% (95% delta interval `[8.75, 14.75]` percentage points), lowers all-candidate query burden from 9.88 to 8.395 (`[-1.715, -1.2625]`), and observes zero selective error with a 1.686% Wilson upper bound. Directional coverage differs by 3 points. This remains synthetic evidence rather than a buyer fallback policy or production rule. |
| Positive-propensity logging design | Horvitz and Thompson (1952) establish unequal-probability weighting; Dudík et al. (2011) and Swaminathan and Joachims (2015) apply logged propensities to partial-feedback policy evaluation while warning about variance. | A fixed-seed ε-greedy simulation gives every candidate probability at least 0.05: the ranked winner receives 0.85 and each other candidate 0.05. It observes every candidate, reports inverse-propensity value RMSE 0.008943, and covers all four known true values with its 95% intervals. Buyer validity remains unexecuted. |

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
Source commit `260fa1dd` then computes the validated query-vector norm once per
decision rather than once for every retained context. Across five before/after
local runs, median candidate p50 fell from `0.023167` to `0.015042` ms (35.07%)
and the median paired latency-delta CI upper bound fell from `0.0008368` to
`0.0006112` ms. Brier, log loss, and regret remained bit-identical. The latency
and production gates remain closed because the interval upper bound is positive.
Source commit `1309b3ce` separates observed failure from absent evidence:
accuracy is `passed`, latency is `failed`, and buyer-heldout plus
measurement-validity gates are `not_executed`. The legacy Boolean view derives
strictly from `status == "passed"`, preserving fail-closed compatibility.
Source commit `c690ebe7` makes the measurement-validity denominator explicit:
scale linking, local independence, correctly oriented candidate-group DIF,
item-side language/domain effects, judge effects, and adaptive exposure must
each carry evidence. All six currently report `not_executed`.
Source commit `fdb8e57a` also separates released owner contracts from the
pending local-independence contract and contracts then classified as
unimplemented. It records the buyer evidence each check still needs without
treating API availability as completed validation; later evidence corrects the
two overly broad classifications below.
Source commit `7edccae0` caches the validated unit vector for each retained
context at observation time. Across five before/after local runs, median
candidate p50 fell from `0.016083` to `0.009791` ms (39.12%) while Brier, log
loss, and regret remained identical. The candidate-minus-baseline latency CI
upper bound remained positive, so the production latency gate stays closed.
Source commit `00b2eef3` corrects the item-side owner status from
`not_implemented` to `released_limited`. The installed `fast-mlsirm` 0.9.1
contract can estimate one multigroup item covariate coefficient; it cannot
claim the richer language-specific discrimination or residual model.
Source commit `a095b41f` similarly separates released CAT exposure control
from the missing gateway observation-design contract. `fast-mlsirm` 0.9.1 can
calibrate an exposure filter, but it cannot reconstruct routing propensities or
unobserved candidate outcomes that CO never recorded.
Source commit `46e15555` adds a secret-free selection-design receipt to route,
conducted-workflow, and streaming trace rows. It binds the ordered candidate
deployments, actual attempts, selected deployment, and policy snapshot while
labeling the current deterministic assignment propensity `not_identified`.
This supplies an auditable observation denominator; it does not identify
counterfactual outcomes or open the adaptive-exposure gate.
Source commit `2c783b98` preregisters a benchmark-only ε-greedy logging policy
with 20% exploration across four candidates and 24,000 fixed-seed trials. Every
candidate receives probability at least 0.05; Horvitz-Thompson estimates reach
RMSE 0.008943 against known synthetic truth and all four 95% intervals cover
their targets. Source `36dbf3bb` adds the missing naive comparison: treating
adaptively selected observations as ignorable yields RMSE `0.321979`, so logged
inverse-propensity estimation reduces error by `0.313036`. This validates
executable propensity arithmetic, not buyer
outcomes, and does not change production selection.
Source commit `ca6e9a75` validates the released common-item linking contract.
Six anchors undergo a known `slope=1.3`, `intercept=-0.4` metric change;
Stocking–Lord linking converges and recovers both coefficients with
true-parameter RMSE `3.24e-16`. These exact synthetic anchors prove the
calculation path, not cross-version buyer invariance, so `scale_linking`
remains `not_executed` for production.
Source commit `d0d81e8f` validates candidate-cohort DIF screening with a
known shifted item. The unpurified screen also flags an invariant item because
the matching total is contaminated; iterative logistic purification stabilizes
with seven anchors, detects the one injected item (recall 1.0), and has zero
false positives. The result is synthetic contract evidence, so buyer DIF stays
`not_executed`.
Source commit `ac28b6d0` validates judge-severity recovery with a connected,
fully crossed 1,000-respondent × 6-item × 3-judge design. The many-facet Rasch
fit converges in five iterations, preserves severity order, and reports RMSE
0.018292 against centered true severities `[-0.7, 0, 0.7]`. Versioned buyer
judges and observed buyer ratings remain absent, so `judge_effects` stays
`not_executed`.

## APA 7 references

Barrada, J. R., Olea, J., & Ponsoda, V. (2007). Methods for restricting maximum
exposure rate in computerized adaptive testing. *Methodology, 3*(1), 14–23.
https://doi.org/10.1027/1614-2241.3.1.14

Chen, W.-H., & Thissen, D. (1997). Local dependence indexes for item pairs
using item response theory. *Journal of Educational and Behavioral Statistics,
22*(3), 265–289. https://doi.org/10.3102/10769986022003265

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*. arXiv.
https://arxiv.org/abs/2305.05176

Debeer, D., & Janssen, R. (2013). Modeling item-position effects within an IRT
framework. *Journal of Educational Measurement, 50*(2), 164–185.
https://doi.org/10.1111/jedm.12009

Doebler, A. (2012). The problem of bias in person parameter estimation in
adaptive testing. *Applied Psychological Measurement, 36*(4), 255–270.
https://doi.org/10.1177/0146621612443304

Finkelman, M., Nering, M. L., & Roussos, L. A. (2009). A conditional exposure
control method for multidimensional adaptive testing. *Journal of Educational
Measurement, 46*(1), 84–103.
https://doi.org/10.1111/j.1745-3984.2009.01070.x

Dudík, M., Langford, J., & Li, L. (2011). Doubly robust policy evaluation and
learning. In *Proceedings of the 28th International Conference on Machine
Learning* (pp. 1097–1104). https://arxiv.org/abs/1103.4601

Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., &
Rubin, D. B. (2013). *Bayesian data analysis* (3rd ed.). CRC Press.

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM
Computer Communication Review, 18*(4), 314–329.
https://doi.org/10.1145/52325.52356

Horvitz, D. G., & Thompson, D. J. (1952). A generalization of sampling without
replacement from a finite universe. *Journal of the American Statistical
Association, 47*(260), 663–685.
https://doi.org/10.1080/01621459.1952.10483446

Jeon, M., Jin, I. H., Schweinberger, M., & Baugh, S. (2021). Mapping
unobserved item–respondent interactions: A latent space item response model
with interaction map. *Psychometrika, 86*(2), 378–403.
https://doi.org/10.1007/s11336-021-09762-5

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

Swaminathan, A., & Joachims, T. (2015). Batch learning from logged bandit
feedback through counterfactual risk minimization. *Journal of Machine Learning
Research, 16*(52), 1731–1755.
https://jmlr.org/papers/v16/swaminathan15a.html

Stocking, M. L., & Lord, F. M. (1983). Developing a common metric in item
response theory. *Applied Psychological Measurement, 7*(2), 201–210.
https://doi.org/10.1177/014662168300700208

French, B. F., & Maller, S. J. (2007). Iterative purification and effect size
use with logistic regression for differential item functioning detection.
*Educational and Psychological Measurement, 67*(3), 373–393.
https://doi.org/10.1177/0013164406294781

Bock, R. D., & Aitkin, M. (1981). Marginal maximum likelihood estimation of
item parameters: Application of an EM algorithm. *Psychometrika, 46*(4),
443–459. https://doi.org/10.1007/BF02293801

Eckes, T. (2015). *Introduction to many-facet Rasch measurement* (2nd ed.).
Peter Lang. https://doi.org/10.3726/978-3-653-04844-5

Linacre, J. M. (1989). *Many-facet Rasch measurement*. MESA Press.

Swaminathan, H., & Rogers, H. J. (1990). Detecting differential item
functioning using logistic regression procedures. *Journal of Educational
Measurement, 27*(4), 361–370.
https://doi.org/10.1111/j.1745-3984.1990.tb00754.x

Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., Lin,
Z., Li, Z., Li, D., Xing, E., Zhang, H., Gonzalez, J. E., & Stoica, I.
(2023). *Judging LLM-as-a-judge with MT-Bench and Chatbot Arena*. arXiv.
https://arxiv.org/abs/2306.05685
