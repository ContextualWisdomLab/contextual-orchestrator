---
title: "Measured routing evidence: latency ledgers, semantic affinity, triage, real-time judging"
status: "proposed; local implementation evidence, protected delivery unverified"
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

### IRT-Router interpretation audit (2026-09-05)

This review separates the ACL 2025 paper from public implementation revision
`e8f258ced4ec3c40d795403603acd8c1cdfb994d`. AERA, APA, and NCME (2014, p. 11)
require support for each intended score interpretation; prediction and ability
measurement are distinct claims. Multidimensional or explanatory IRT is not
rejected merely for using multiple abilities or covariates.

| Evidence | Supported reading | Unmet interpretation requirement |
| --- | --- | --- |
| Paper §3.2 connects monotonicity with interpretability. | A directional response constraint is an interpretable modeling choice. | Validate the named construct, measurement unit, and intended use separately. |
| Paper Eq. (4) prints a linear discrimination transform; public MIRT code lines 51–59 add softplus or a range-scaled sigmoid. | The default implementation has positive discrimination; a configured range must also be positive. | Do not describe the implementation as unconstrained, or infer invariant scales from a positive direction. |
| Figure 4 compares the mean of 25 fitted ability coordinates. | The figure describes one fitted representation. | Identify the coordinate units and justify aggregation before calling that mean comparable general ability. |
| §4.2.2 and Appendix C assign ability labels using five sampled questions per cluster and GPT-4o Mini. | The labels are a proposed content mapping. | Validate that mapping and its coverage before interpreting a named dimension as measured ability. |

An algebraic counterexample clarifies the aggregation issue. In the printed
Eq. (5), the logit is `aᵀθ - b`. For any positive diagonal matrix `C`, replacing
`θ` with `Cθ` and `a` with `C⁻¹a` leaves that logit unchanged for every pair.
For two illustrative ability vectors `(2, 0)` and `(0, 1)`, their averages are
`1` and `0.5`. Rescaling by `C = diag(0.1, 10)` changes the averages to `0.1`
and `5`, reversing their order without changing predictions when discrimination
is transformed inversely. Positive discrimination stays positive.
This is a hand-checkable mathematical example, not empirical LLM data,
checkpoint manipulation, or a proof that every neural parameter constraint
admits the same transformation. The constrained implementation still needs its
own identification analysis; an arbitrary coordinate average is not justified
by predictive loss alone.

The gateway consequently treats IRT-Router as a response-prediction reference,
not a certificate of stable ability. Missing validation is not a demonstrated
assumption violation. Buyer evidence must separately establish construct and
item-content coverage, identification and linking, fit and residual dependence,
appropriate candidate-group or item-side invariance, and estimation uncertainty.

The existing default-change input helper was also audited. RED `76908a55`
reproduced ten invalid approvals and two unhandled numeric-overflow cases.
Source `0ad54cdf` reuses the existing finite-number validator, requires explicit
`measured` status, rejects negative candidate RMSE and nonpositive baseline RMSE,
and retains the 55% improvement requirement and valid zero candidate error.
The 52-test profile suite passed with 100% statement and branch coverage.
This helper checks declarations only: it neither authenticates observation
provenance nor changes production defaults. Its `True` result cannot replace
buyer measurement validation, independent review, or protected release approval.
The separate held-out routing harness continues to require all its own gates.

### Existing implementation evidence

| Implementation boundary | Evidence-informed reason | Acceptance evidence |
| --- | --- | --- |
| EWMA with gain 1/8 for latency and throughput | Jacobson's congestion-avoidance estimator is the canonical low-pass filter for volatile network measurements; it needs no tuning window. | Exact-arithmetic tests reproduce hand-computed EWMA values. |
| Laplace rule of succession as stability prior | Beta(1,1) is an explicit uniform-prior assumption, not a uniquely assumption-free estimate (Gelman et al., 2013). | Stability tests assert alpha/(alpha+beta) exactly; arithmetic does not validate that prior for buyer outcomes. |
| Cosine similarity over declared metadata documents | Karpukhin et al. (2020, Section 3.1) use learned dense representations and dot-product similarity. CO's normalized cosine over operator-declared descriptors is a separate adaptation, not their validated routing method. | Deterministic mock-embedding tests verify cosine ordering and zero-vector guards. |
| Strict JSON triage verdict | Zheng et al. (2023) study judge agreement and position, verbosity, self-enhancement, and reasoning limitations. The exact JSON contract is CO's fail-closed parsing decision; syntactic validity cannot establish judgment accuracy. | Parser tests reject seven malformed-reply classes and cache verdicts by content hash; buyer judge calibration remains separate. |
| Probability calibration | Cox (1958) motivates logistic recalibration; Arrieta-Ibarra et al. (2022) distinguish calibration diagnostics from aggregate probabilistic scores. | Source `92b9309b` moves held-out calibration slope from `0.991445` to `1.014030` and reduces logit RMSE from `0.231235` to `0.025803`; the paired improvement interval is `[-0.208030, -0.202924]`. Synthetic truth does not replace buyer outcome calibration. |
| Real-time judging before returning answers | RouteLLM/FrugalGPT motivate quality-aware routing between models (Ong et al., 2024; Chen et al., 2023); here quality is measured per deployment instead of trained offline. | Judge-driven failover tests prove rejection routes to the next candidate within budget while updating both ledgers. |
| Candidate-specific evidence and interactions | Jeon et al. (2021) model item–respondent interactions in a latent metric space. Separate per-member ledgers do not implement that model or by themselves prevent cross-level inference errors; buyer hierarchy, dependence, and generalization need separate evidence. | Quality-ledger reports expose per-member posteriors; their existence does not establish a multilevel measurement model. |
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
| Classification-oriented stopping and rejection | Luo, Kim, and Dickison (2018) describe CI stopping; Chow (1970) and El-Yaniv and Wiener (2010) frame abstention as an error–coverage tradeoff; Morris, White, and Crowther (2019) require Monte Carlo uncertainty for simulated performance. | Source `e1ff2e61` chooses `z=1.645` on a development seed. Source `609faff8` rejects it after only 20% of ten independent runs satisfy the declared error ceiling. Source `1862893a` reports that pass-rate estimate's MCSE as 0.1265 and requires 400 worst-case replications for a 0.025 MCSE; coverage-delta, query-delta, and risk MCSEs are 0.00619, 0.02257, and 0.00211. Ten seeds expose instability but do not precisely estimate its operating characteristics. Buyer fallback policy, adequately powered preregistration, calibrated intervals, and live latency remain unexecuted. |
| Decision-time implementation cost | The accuracy experiment must also beat the existing one-neighbor route-decision wall time without changing fitted scores or cosine semantics. | Source `0b87905c` replaces a Python generator with `map(operator.mul, ...)` inside the existing `math.fsum`. Across ten before/after process runs, candidate p50 median falls from 0.01325 to 0.007708 ms (41.83%) and the latency-delta CI-upper median falls from 0.000910 to 0.000635 ms (30.14%). The delta remains positive, so the latency gate still fails; this is local CPU timing, not end-to-end provider latency. |
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

Run `uv run --python 3.12 python scripts/benchmark_psychometric_heldout.py` for the separate,
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

## Review correction evidence (2026-09-05)

The review of source `6d1b30803888e893d7bdbdf4d12605a16c36162d`
found literal subgroup denominators tied to 400 candidates. RED commit
`43706aad` reproduces coverage above 100% at 401 and 403 candidates.
Source `a8109a65` derives all three subgroup sizes from the same generated
trait grid used by the experiment and subtracts directional rates rather than
counts. Empty or unresolved summaries fail explicitly; they are never reported
as zero error. Default candidate counts, response seeds, repetitions, and
admission gates are unchanged. These are harness corrections, not new
estimators or evidence of buyer accuracy.

The full suite using executable source `a8109a65` finished with 3,432 passing
tests, two skips, and exit 0 in 728.31 seconds, including the existing
full-size experiment assertions. Documentation edits were checked separately
with 102 passing routing, paper, and boundary tests. Hosted acceptance and
buyer calibration remain unverified.

The same source keeps nearest-rank observation p95 dependent on the actual
sample count (101 by default) and shares the Python 3.12 startup guard before
optional numerical imports. The race-reentry regression confirms that a
deployment called again after race failure must occur again in the selection
receipt. The receipt records selection attempts, not a unique deployment set
or a complete transport/tool-retry ledger; its multiplicity cannot be discarded
or used alone to certify all provider costs or an exposure probability.

The research table now separates source findings from CO-specific choices:
Beta(1,1) remains an assumption; DPR's dot product is not this gateway's cosine
policy; a JSON parser does not validate a judge; and per-member ledgers do not
prove a multilevel model. The ADR diagram separates the production
single-neighbor default from opt-in two-neighbor held-out experiments.

## APA 7 references

American Educational Research Association, American Psychological
Association, & National Council on Measurement in Education. (2014).
*Standards for educational and psychological testing*. American Educational
Research Association. https://www.testingstandards.net/open-access-files.html

Arrieta-Ibarra, I., Gujral, P., Tannen, J., Tygert, M., & Xu, C. (2022).
Metrics of calibration for probabilistic predictions. *Journal of Machine
Learning Research, 23*(351), 1–54.
https://www.jmlr.org/papers/v23/22-0658.html

Babcock, B., & Albano, A. D. (2012). Rasch scale stability in the presence of
item parameter and trait drift. *Applied Psychological Measurement, 36*(7),
565–580. https://doi.org/10.1177/0146621612455090

Barrada, J. R., Olea, J., & Ponsoda, V. (2007). Methods for restricting maximum
exposure rate in computerized adaptive testing. *Methodology, 3*(1), 14–23.
https://doi.org/10.1027/1614-2241.3.1.14

Bechger, T. M., Maris, G., Verstralen, H. H. F. M., & Béguin, A. A. (2003).
Using classical test theory in combination with item response theory.
*Applied Psychological Measurement, 27*(5), 319–334.
https://doi.org/10.1177/0146621603257518

Bock, R. D., & Aitkin, M. (1981). Marginal maximum likelihood estimation of
item parameters: Application of an EM algorithm. *Psychometrika, 46*(4),
443–459. https://doi.org/10.1007/BF02293801

Bock, R. D., & Mislevy, R. J. (1982). Adaptive EAP estimation of ability in
a microcomputer environment. *Applied Psychological Measurement, 6*(4),
431–444. https://doi.org/10.1177/014662168200600405

Brogden, H. E. (1949). When testing pays off. *Personnel Psychology, 2*(2),
171–183. https://doi.org/10.1111/j.1744-6570.1949.tb01397.x

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*. arXiv.
https://arxiv.org/abs/2305.05176

Chen, W.-H., & Thissen, D. (1997). Local dependence indexes for item pairs
using item response theory. *Journal of Educational and Behavioral Statistics,
22*(3), 265–289. https://doi.org/10.3102/10769986022003265

Chen, Y., Lee, Y.-H., & Li, X. (2022). Item pool quality control in
educational testing: Change point model, compound risk, and sequential
detection. *Journal of Educational and Behavioral Statistics, 47*(3),
322–352. https://doi.org/10.3102/10769986211059085

Chow, C. K. (1970). On optimum recognition error and reject tradeoff. *IEEE
Transactions on Information Theory, 16*(1), 41–46.
https://doi.org/10.1109/TIT.1970.1054406

Cox, D. R. (1958). Two further applications of a model for binary regression.
*Biometrika, 45*(3–4), 562–565.
https://doi.org/10.1093/biomet/45.3-4.562

Debeer, D., & Janssen, R. (2013). Modeling item-position effects within an IRT
framework. *Journal of Educational Measurement, 50*(2), 164–185.
https://doi.org/10.1111/jedm.12009

Doebler, A. (2012). The problem of bias in person parameter estimation in
adaptive testing. *Applied Psychological Measurement, 36*(4), 255–270.
https://doi.org/10.1177/0146621612443304

Dudík, M., Langford, J., & Li, L. (2011). Doubly robust policy evaluation and
learning. In *Proceedings of the 28th International Conference on Machine
Learning* (pp. 1097–1104). https://arxiv.org/abs/1103.4601

Eckes, T. (2015). *Introduction to many-facet Rasch measurement* (2nd ed.).
Peter Lang. https://doi.org/10.3726/978-3-653-04844-5

El-Yaniv, R., & Wiener, Y. (2010). On the foundations of noise-free selective
classification. *Journal of Machine Learning Research, 11*, 1605–1641.
https://www.jmlr.org/papers/v11/el-yaniv10a.html

Finkelman, M., Nering, M. L., & Roussos, L. A. (2009). A conditional exposure
control method for multidimensional adaptive testing. *Journal of Educational
Measurement, 46*(1), 84–103.
https://doi.org/10.1111/j.1745-3984.2009.01070.x

French, B. F., & Maller, S. J. (2007). Iterative purification and effect size
use with logistic regression for differential item functioning detection.
*Educational and Psychological Measurement, 67*(3), 373–393.
https://doi.org/10.1177/0013164406294781

Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., &
Rubin, D. B. (2013). *Bayesian data analysis* (3rd ed.). CRC Press.

Guo, R., Zheng, Y., & Chang, H.-H. (2015). A stepwise test characteristic
curve method to detect item parameter drift. *Journal of Educational
Measurement, 52*(3), 280–300. https://doi.org/10.1111/jedm.12077

Hau, K.-T., & Chang, H.-H. (2001). Item selection in computerized adaptive
testing: Should more discriminating items be used first? *Journal of
Educational Measurement, 38*(3), 249–266.
https://doi.org/10.1111/j.1745-3984.2001.tb01126.x

He, Y., & Qi, Y. (2023). Using response time in multidimensional computerized
adaptive testing. *Journal of Educational Measurement, 60*(4), 697–738.
https://doi.org/10.1111/jedm.12373

Horn, J. L. (1965). A rationale and test for the number of factors in factor
analysis. *Psychometrika, 30*(2), 179–185.
https://doi.org/10.1007/BF02289447

Horvitz, D. G., & Thompson, D. J. (1952). A generalization of sampling without
replacement from a finite universe. *Journal of the American Statistical
Association, 47*(260), 663–685.
https://doi.org/10.1080/01621459.1952.10483446

Huebner, A., & Lucht, M. (2019). Generalizability theory in R. *Practical
Assessment, Research, and Evaluation, 24*, Article 5.
https://openpublishing.library.umass.edu/pare/article/id/1593/

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM
Computer Communication Review, 18*(4), 314–329.
https://doi.org/10.1145/52325.52356

Jeon, M., Jin, I. H., Schweinberger, M., & Baugh, S. (2021). Mapping
unobserved item–respondent interactions: A latent space item response model
with interaction map. *Psychometrika, 86*(2), 378–403.
https://doi.org/10.1007/s11336-021-09762-5

Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D.,
& Yih, W.-t. (2020). Dense passage retrieval for open-domain question
answering. In *Proceedings of the 2020 Conference on Empirical Methods in
Natural Language Processing* (pp. 6769–6781). Association for
Computational Linguistics. https://doi.org/10.18653/v1/2020.emnlp-main.550

Laplace, P.-S. (1774). Mémoire sur la probabilité des causes par les
événements. *Mémoires de l'Académie Royale des Sciences de Paris, 6*,
621–656. (Rule of succession; modern treatment in Gelman et al., 2013.)

Linacre, J. M. (1989). *Many-facet Rasch measurement*. MESA Press.

Lior, G., Frostig, T., Stanovsky, G., & Eyal, M. (2026). *Extending item
response theory for efficient and meaningful multilingual evaluation*
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2606.15643

Lord, F. M. (1950). *Properties of test scores expressed as functions of the
item parameters* (Research Bulletin RB-50-56). Educational Testing Service.
https://doi.org/10.1002/j.2333-8504.1950.tb00919.x

Luo, X., Kim, D., & Dickison, P. (2018). Projection-based stopping rules for
computerized adaptive testing in licensure testing. *Applied Psychological
Measurement, 42*(4), 275–290.
https://doi.org/10.1177/0146621617726790

Magis, D. (2013). A note on the item information function of the
four-parameter logistic model. *Applied Psychological Measurement, 37*(4),
304–315. https://doi.org/10.1177/0146621613475471

Maydeu-Olivares, A., & Joe, H. (2005). Limited- and full-information
estimation and goodness-of-fit testing in 2ⁿ contingency tables: A unified
framework. *Journal of the American Statistical Association, 100*(471),
1009–1020. https://doi.org/10.1198/016214504000002069

Meijer, R. R. (1996). Person-fit research: An introduction. *Applied
Measurement in Education, 9*(1), 3–8.
https://doi.org/10.1207/s15324818ame0901_2

Millsap, R. E. (2010). Testing measurement invariance using item response
theory in longitudinal data: An introduction. *Child Development
Perspectives, 4*(1), 5–9.
https://doi.org/10.1111/j.1750-8606.2009.00109.x

Morris, T. P., White, I. R., & Crowther, M. J. (2019). Using simulation
studies to evaluate statistical methods. *Statistics in Medicine, 38*(11),
2074–2102. https://doi.org/10.1002/sim.8086

Moses, T. P., & Holland, P. W. (2008). *Notes on a general framework for
observed score equating* (Research Report No. RR-08-59). Educational Testing
Service. https://doi.org/10.1002/j.2333-8504.2008.tb02145.x

Nadaraya, E. A. (1964). On estimating regression. *Theory of Probability &
Its Applications, 9*(1), 141–142. https://doi.org/10.1137/1109020

Oakes, D. (1999). Direct calculation of the information matrix via the EM.
*Journal of the Royal Statistical Society: Series B, 61*(2), 479–482.
https://doi.org/10.1111/1467-9868.00188

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs
with preference data*. arXiv. https://arxiv.org/abs/2406.18665

Pritikin, J. N. (2017). A comparison of parameter covariance estimation
methods for item response models in an expectation-maximization framework.
*Cogent Psychology, 4*(1), 1279435.
https://doi.org/10.1080/23311908.2017.1279435

Rudner, L. M. (2001). Computing the expected proportions of misclassified
examinees. *Practical Assessment, Research & Evaluation, 7*(14), 1–5.
https://doi.org/10.7275/an9m-2035

Rudner, L. M. (2005). Expected classification accuracy. *Practical
Assessment, Research & Evaluation, 10*(13), 1–4.
https://doi.org/10.7275/56a5-6b14

Song, W., Huang, Z., Cheng, C., Gao, W., Xu, B., Zhao, G., Wang, F., & Wu, R.
(2025). IRT-Router: Effective and interpretable multi-LLM routing via item
response theory. In *Proceedings of the 63rd Annual Meeting of the Association
for Computational Linguistics (Volume 1: Long Papers)* (pp. 15629–15644).
Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.acl-long.761

Stanley, L. M., & Edwards, M. C. (2016). Reliability and model fit.
*Educational and Psychological Measurement, 76*(6), 976–985.
https://doi.org/10.1177/0013164416638900

Stenhaug, B. A., & Domingue, B. W. (2022). Predictive fit metrics for item
response models. *Applied Psychological Measurement, 46*(2), 128–143.
https://doi.org/10.1177/01466216211066603

Stocking, M. L., & Lord, F. M. (1983). Developing a common metric in item
response theory. *Applied Psychological Measurement, 7*(2), 201–210.
https://doi.org/10.1177/014662168300700208

Swaminathan, A., & Joachims, T. (2015). Batch learning from logged bandit
feedback through counterfactual risk minimization. *Journal of Machine Learning
Research, 16*(52), 1731–1755.
https://jmlr.org/papers/v16/swaminathan15a.html

Swaminathan, H., & Rogers, H. J. (1990). Detecting differential item
functioning using logistic regression procedures. *Journal of Educational
Measurement, 27*(4), 361–370.
https://doi.org/10.1111/j.1745-3984.1990.tb00754.x

Taylor, H. C., & Russell, J. T. (1939). The relationship of validity
coefficients to the practical effectiveness of tests in selection:
Discussion and tables. *Journal of Applied Psychology, 23*(5), 565–578.
https://doi.org/10.1037/h0057079

Tendeiro, J. N., Meijer, R. R., & Niessen, A. S. M. (2016). PerFit: An R
package for person-fit analysis in IRT. *Journal of Statistical Software,
74*(5), 1–27. https://doi.org/10.18637/jss.v074.i05

Tinsley, H. E. A., & Dawis, R. V. (1975). An investigation of the Rasch
simple logistic model: Sample free item and test calibration. *Educational
and Psychological Measurement, 35*(2), 325–336.
https://doi.org/10.1177/001316447503500211

Tran, U. S., & Formann, A. K. (2009). Performance of parallel analysis in
retrieving unidimensionality in the presence of binary data. *Educational
and Psychological Measurement, 69*(1), 50–61.
https://doi.org/10.1177/0013164408318761

Xu, J., Paek, I., & Xia, Y. (2017). Investigating the behaviors of M2 and
RMSEA2 in fitting a unidimensional model to multidimensional data. *Applied
Psychological Measurement, 41*(8), 632–644.
https://doi.org/10.1177/0146621617710464

Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., Lin,
Z., Li, Z., Li, D., Xing, E., Zhang, H., Gonzalez, J. E., & Stoica, I.
(2023). *Judging LLM-as-a-judge with MT-Bench and Chatbot Arena*. arXiv.
https://arxiv.org/abs/2306.05685
