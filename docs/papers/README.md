# Papers grounding the cost-review + routing hub

These papers ground the design of the LLM **cost review** ledger and the
**sync-vs-batch / upstream** routing added in `feat/cost-review-and-batch-routing`.
Vendored PDFs are limited to papers whose redistribution terms were checked;
the remaining sources are cited and linked without copying their files.

## Cost optimisation

- **FrugalGPT: How to Use Large Language Models While Reducing Cost and
  Improving Performance** — Lingjiao Chen, Matei Zaharia, James Zou. arXiv:2305.05176, 2023.
  `frugalgpt-cost-2305.05176.pdf`
  Motivates the **configurable price table + per-request cost accounting** and
  cost-optimising model selection: cost varies by orders of magnitude across
  providers/models, so a gateway should price each request and route to the
  cheapest capable upstream. Distributed under arXiv's non-exclusive license to
  distribute (arXiv perpetual, non-exclusive license 1.0).
  TMLR record: https://openreview.net/forum?id=cSimKw5p6R

## Query routing (which upstream / which tier)

- **RouteLLM: Learning to Route LLMs with Preference Data** — Isaac Ong, Amjad
  Almahairi, Vincent Wu, Wei-Lin Chiang, Tianhao Wu, Joseph E. Gonzalez, M.
  Waleed Kadous, Ion Stoica. arXiv:2406.18665, 2024.
  `routellm-routing-2406.18665.pdf`
  Grounds the **routing decision** layer (`RoutingPolicy` + cost-aware upstream
  selection): route strong/weak model choices to hit a cost/quality target.
  arXiv preprint; distributed under the arXiv non-exclusive distribution license.

- **Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing** — Dujian Ding,
  Ankur Mallick, Chi Wang, Robert Sim, Subhabrata Mukherjee, Victor Rühle,
  Laks V. S. Lakshmanan, Ahmed Hassan Awadallah. arXiv:2404.14618 (ICLR 2024).
  `hybrid-llm-query-routing-2404.14618.pdf`
  Grounds **latency-tolerant vs interactive routing** and the sync/batch split:
  route easy/bulk queries to the cheaper path, keep hard/interactive queries on
  the responsive path. Distributed under the arXiv non-exclusive license /
  CC BY as marked on arXiv.

## Role reasoning-effort profiles

Issue #568 needs a provider-neutral `reasoning_effort_profile` so Fugu-style
route versus Fugu-Ultra conduct, TRINITY roles, and Conductor steps can share
one replayable compute snapshot. PDFs are cited rather than vendored when
redistribution is unclear.

- Sakana AI. (2026). *Sakana Fugu Technical Report*.
  https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
  Grounds the latency-quality frontier: route is the low-compute path,
  conduct is the high-quality path. Do not proxy that split with temperature.
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
  *Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
  https://arxiv.org/abs/2512.04695
  Grounds thinker / worker / verifier (plus synthesizer, planner, judge)
  role bindings on the catalog.
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
  *Learning to orchestrate agents in natural language with the Conductor*
  (arXiv:2512.04388). https://arxiv.org/abs/2512.04388
  Grounds workflow steps, recursion depth, decomposition, and access-list
  scope as first-class ablation factors.
- Baker, F. B. (2001). *The basics of item response theory* (2nd ed.).
  ERIC Clearinghouse on Assessment and Evaluation.
  https://eric.ed.gov/?id=ED458219
  Grounds RMSE(θ̂, θ) as the accuracy metric. The ablation must emit θ̂
  and compare it to known true parameters; a rank constant is not an estimate.

Buyer next action: call `run_equal_budget_ablation` and read
`production_default_change_allowed` before changing live defaults.

## Psychometric routing accuracy-time frontier

- Cox, D. R. (1958). Two further applications of a model for binary regression.
  *Biometrika, 45*(3–4), 562–565.
  https://doi.org/10.1093/biomet/45.3-4.562
- Arrieta-Ibarra, I., Gujral, P., Tannen, J., Tygert, M., & Xu, C. (2022).
  Metrics of calibration for probabilistic predictions. *Journal of Machine
  Learning Research, 23*(351), 1–54.
  https://www.jmlr.org/papers/v23/22-0658.html
  Ground checking whether routing probabilities retain their stated meaning,
  separately from ranking and aggregate proper scores. Source `92b9309b`
  reduces paired held-out logit calibration RMSE from `0.231235` to `0.025803`;
  the 95% candidate-minus-baseline interval is `[-0.208030, -0.202924]`.
- Song, W., Huang, Z., Cheng, C., Gao, W., Xu, B., Zhao, G., Wang, F., & Wu,
  R. (2025). *IRT-Router: Effective and interpretable multi-LLM routing via
  item response theory* [Preprint]. arXiv.
  https://doi.org/10.48550/arXiv.2506.01048
  Motivates held-out response prediction from candidate-query interactions;
  exact-query and semantic warm-start evidence must be evaluated separately.
  CO classifies this as an IRT-shaped predictive model, not a validated
  psychometric measurement model: monotonicity alone does not identify a scale
  or establish construct validity, and the paper's selected model-pair and
  two-query examples do not supply uncertainty or invariant measurement proof.
  In its MIRT equation, the query discrimination vector is an unconstrained
  learned transform of the query embedding. The paper does not establish a
  positive orientation for each coordinate, so increasing one fitted ability
  coordinate need not increase the predicted success probability. Its
  25-dimensional coordinates also lack anchors or another reported
  identification convention that would make their axes invariant to rotation,
  reflection, or rescaling. Binary cross-entropy prediction and face-valid
  examples therefore cannot, by themselves, prove the claimed monotonic or
  construct interpretation.
  The gateway does not adopt the paper's stronger interpretation of fitted
  coordinates as stable LLM abilities or query properties. The paper and its
  public implementation report predictive metrics, but do not establish scale
  linking, parameter invariance, local independence, DIF, parameter uncertainty,
  rater effects, or adaptive-routing selection-bias control. Until those checks
  exist, fitted values remain deployment- and sample-conditional routing
  evidence rather than psychometric measurements that can be compared across
  model versions, provider policies, domains, or time.
  Source commit `0f875e3f` exercises the released item-side covariate contract
  against a known coefficient. It converges after 941 iterations and estimates
  `-0.789650` for true `-0.8` (absolute error `0.010350`). This synthetic
  recovery still does not establish buyer or invariant-scale validity.
- Oakes, D. (1999). Direct calculation of the information matrix via the EM.
  *Journal of the Royal Statistical Society: Series B, 61*(2), 479–482.
  https://doi.org/10.1111/1467-9868.00188
  Grounds the observed-information calculation reused by the released
  `fast-mlsirm` standard-error API.
- Pritikin, J. N. (2017). A comparison of parameter covariance estimation
  methods for item response models in an expectation-maximization framework.
  *Cogent Psychology, 4*(1), 1279435.
  https://doi.org/10.1080/23311908.2017.1279435
  Supports checking Oakes covariance estimates for accuracy and elapsed time in
  item-factor models. Source commit `b0f3703f` recovers six known item
  intercepts with RMSE `0.039160`; all six 95% Wald intervals cover their true
  values and have mean width `0.295945`. The released API conditions on
  population parameters and rejects anchors, zero inflation, and item
  covariates, so buyer uncertainty remains unexecuted.
- Millsap, R. E. (2010). Testing measurement invariance using item response
  theory in longitudinal data: An introduction. *Child Development
  Perspectives, 4*(1), 5–9.
  https://doi.org/10.1111/j.1750-8606.2009.00109.x
  Grounds the requirement that relations between observed outcomes and the
  latent routing construct remain invariant across recalibrations.
- Babcock, B., & Albano, A. D. (2012). Rasch scale stability in the presence of
  item parameter and trait drift. *Applied Psychological Measurement, 36*(7),
  565–580. https://doi.org/10.1177/0146621612455090
  Grounds the warning that drift in common items can distort linked scores and
  classifications. Source commit `2e129e2a` links two known parameter sets
  through seven stable anchors, flags the one injected drift item, and produces
  no stable-item false positive. Its fixed `0.25` tolerance is a preregistered
  effect-size screen, not an inferential cutoff or buyer invariance proof.
- Tinsley, H. E. A., & Dawis, R. V. (1975). An investigation of the Rasch
  simple logistic model: Sample free item and test calibration. *Educational
  and Psychological Measurement, 35*(2), 325–336.
  https://doi.org/10.1177/001316447503500211
  Grounds checking whether calibration survives a changed respondent sample
  and ties any invariance claim to adequate sampling, design, and model fit.
  Source commit `5c6ba17a` separately fits 20- and 16-candidate synthetic
  rosters, links 200 common items, and reports linked common-score RMSE
  `0.010866`, correlation `0.999999`, and maximum shift `0.016498`. Buyer
  roster invariance remains unexecuted.
- Huebner, A., & Lucht, M. (2019). Generalizability theory in R. *Practical
  Assessment, Research, and Evaluation, 24*, Article 5.
  https://openpublishing.library.umass.edu/pare/article/id/1593/
  Grounds the crossed persons-by-items-by-occasions G-study and D-study used to
  distinguish candidate signal from query, repeat, and interaction error.
  Source commit `015c4bf6` raises synthetic dependability from `0.401565` for
  one query and one occasion to `0.849616` for 12 queries and four occasions;
  a balanced synthetic tensor does not establish buyer generalizability.
- Guo, R., Zheng, Y., & Chang, H.-H. (2015). A stepwise test characteristic
  curve method to detect item parameter drift. *Journal of Educational
  Measurement, 52*(3), 280–300. https://doi.org/10.1111/jedm.12077
  Grounds judging drift by its aggregate test-function impact rather than item
  parameter distance alone. Source commit `c7c4a13f` detects the one injected
  drift item and reduces synthetic TCC-area difference from `0.123355` to zero.
  The released backward-only heuristic uses a fixed threshold and is not the
  paper's complete entry-and-removal procedure.
- American Educational Research Association, American Psychological
  Association, & National Council on Measurement in Education. (2014).
  *Standards for educational and psychological testing*. American Educational
  Research Association. https://www.testingstandards.net/open-access-files.html
  Standards 5.16–5.18 require evidence that scores retain comparable meaning
  across alternate item sets and that linking limitations are documented.
- Moses, T. P., & Holland, P. W. (2008). Notes on a general framework for
  observed score equating (Research Report No. RR-08-59). Educational Testing
  Service. https://doi.org/10.1002/j.2333-8504.2008.tb02145.x
  Grounds observed-score equating and its uncertainty boundary. Source commit
  `1dce9688` recovers a known slope `2` and intercept `1`: raw cross-form RMSE
  `6.782330` falls to zero, and 300-bootstrap 95% intervals cover all 11 known
  equivalent scores. Comparable buyer populations or anchors remain required.
- Meijer, R. R. (1996). Person-fit research: An introduction. *Applied
  Measurement in Education, 9*(1), 3–8.
  https://doi.org/10.1207/s15324818ame0901_2
  Grounds examining response patterns that deviate from the fitted model or
  comparison group instead of trusting every fitted candidate coordinate.
- Tendeiro, J. N., Meijer, R. R., & Niessen, A. S. M. (2016). PerFit: An R
  package for person-fit analysis in IRT. *Journal of Statistical Software,
  74*(5), 1–27. https://doi.org/10.18637/jss.v074.i05
  Grounds the released nonparametric person-fit statistics. Source commit
  `a18e25f7` ranks one injected inverted response pattern first among 1,000
  candidates with ZU3 separation `1.818719` from the next-highest pattern. The
  diagnostic does not explain the anomaly or supply a universal action cutoff,
  so buyer response-pattern fit remains unexecuted.
- Rudner, L. M. (2001). Computing the expected proportions of misclassified
  examinees. *Practical Assessment, Research & Evaluation, 7*(14), 1–5.
  https://doi.org/10.7275/an9m-2035
- Rudner, L. M. (2005). Expected classification accuracy. *Practical
  Assessment, Research & Evaluation, 10*(13), 1–4.
  https://doi.org/10.7275/56a5-6b14
  Ground expected classification accuracy and consistency in the score-error
  distribution around a declared decision cut. Source commit `0b19116e`
  raises expected accuracy from `0.814182` to `0.996895` and consistency from
  `0.710275` to `0.993829` when synthetic standard error falls from `0.8` to
  `0.2`. The cut and costs are synthetic, so buyer decisions remain unexecuted.
- Taylor, H. C., & Russell, J. T. (1939). The relationship of validity
  coefficients to the practical effectiveness of tests in selection:
  Discussion and tables. *Journal of Applied Psychology, 23*(5), 565–578.
  https://doi.org/10.1037/h0057079
  Grounds the joint reporting of predictive validity, selection ratio, base
  rate, and expected selected success. Source commit `452a3649` pairs that
  result with the released Brogden-Cronbach-Gleser utility analogue: raising
  validity from `0.2` to `0.6` raises synthetic selected success from
  `0.500273` to `0.723515`, but an `8,000`-unit cost increase turns net utility
  from `5,626.64` to `-2,373.36`. Personnel selection is only an analogue;
  buyer-valued routing outcomes and costs remain unvalidated.
- Stenhaug, B. A., & Domingue, B. W. (2022). Predictive fit metrics for item
  response models. *Applied Psychological Measurement, 46*(2), 128–143.
  https://doi.org/10.1177/01466216211066603
  Separates prediction of missing responses for observed persons from prediction
  of complete responses for new persons. Source commit `68831dff` maps those
  tasks to unseen queries for known deployments and unseen candidate deployments.
  Source commit `54833bd8` executes the latter path across 24 contexts and
  records zero psychometric prediction coverage. It therefore cannot claim
  cold-start predictive fit for a newly introduced or changed deployment.
- Chen, Y., Lee, Y.-H., & Li, X. (2022). Item pool quality control in
  educational testing: Change point model, compound risk, and sequential
  detection. *Journal of Educational and Behavioral Statistics, 47*(3),
  322–352. https://doi.org/10.3102/10769986211059085
  Grounds monitoring psychometric drift as a sequential decision with explicit
  false-detection and missed-detection risks. Source commit `7c3e6e98` runs a
  narrower one-stream Bernoulli CUSUM calculation over 500 seeded repetitions.
  Source commit `1b3b7244` searches 11 thresholds on 500 calibration runs using
  a 95% Wilson false-alarm upper bound, then evaluates the selected `6.6`
  threshold on an independent 500-run seed. Held-out false alarms are `2.4%`
  with upper bound `4.15%`; delay p50 is 10 and p95 is 20 observations. It is
  not the paper's multistream Bayesian procedure and supplies no buyer threshold.
- Horn, J. L. (1965). A rationale and test for the number of factors in factor
  analysis. *Psychometrika, 30*(2), 179–185.
  https://doi.org/10.1007/BF02289447
  Grounds comparison of observed roots with roots attributable to sampling
  error. Source commit `73e07a8e` recovers both known dimensions in a seeded
  1,000-response, 12-item simulation.
- Tran, U. S., & Formann, A. K. (2009). Performance of parallel analysis in
  retrieving unidimensionality in the presence of binary data. *Educational
  and Psychological Measurement, 69*(1), 50–61.
  https://doi.org/10.1177/0013164408318761
  Grounds the limitation: Pearson-correlation parallel analysis can perform
  poorly on binary items. CO therefore treats the result as a synthetic screen,
  not construct identification or buyer-validity evidence.
- Maydeu-Olivares, A., & Joe, H. (2005). Limited- and full-information
  estimation and goodness-of-fit testing in 2ⁿ contingency tables: A unified
  framework. *Journal of the American Statistical Association, 100*(471),
  1009–1020. https://doi.org/10.1198/016214504000002069
  Grounds limited-information global model-fit testing for binary response
  tables. Source commit `7f13dc7d` yields M2 `45.744317` (`p=0.105619`) for a
  fitted one-factor design and M2 `287.163678` (`p≈2.27e-41`) when the same
  one-factor model is fitted to known two-factor data.
- Xu, J., Paek, I., & Xia, Y. (2017). Investigating the behaviors of M2 and
  RMSEA2 in fitting a unidimensional model to multidimensional data. *Applied
  Psychological Measurement, 41*(8), 632–644.
  https://doi.org/10.1177/0146621617710464
  Grounds the limitation that M2 sensitivity varies with the multidimensional
  structure. A detected synthetic misspecification therefore does not establish
  buyer construct validity or universal model-fit thresholds.
- Bechger, T. M., Maris, G., Verstralen, H. H. F. M., & Béguin, A. A. (2003).
  Using classical test theory in combination with item response theory.
  *Applied Psychological Measurement, 27*(5), 319–334.
  https://doi.org/10.1177/0146621603257518
  Grounds posterior-variance decomposition as an empirical score-reliability
  summary. Source commit `5b50e10c` raises reliability from `0.366437` to
  `0.800436` when true item discrimination increases from `0.45` to `1.5`.
- Stanley, L. M., & Edwards, M. C. (2016). Reliability and model fit.
  *Educational and Psychological Measurement, 76*(6), 976–985.
  https://doi.org/10.1177/0013164416638900
  Grounds treating reliability and model fit as distinct evidence. High score
  precision cannot repair a misspecified model or establish validity.
- Lord, F. M. (1950). *Properties of test scores expressed as functions of the
  item parameters* (Research Bulletin RB-50-56). Educational Testing Service.
  https://doi.org/10.1002/j.2333-8504.1950.tb00919.x
  Grounds reporting measurement error and discriminating power at specified
  ability levels rather than only as one sample average.
- Magis, D. (2013). A note on the item information function of the
  four-parameter logistic model. *Applied Psychological Measurement, 37*(4),
  304–315. https://doi.org/10.1177/0146621613475471
  Grounds the released item/test information calculation. Source commit
  `b4efa489` spreads 12 item difficulties across `[-2, 2]`, improving the
  worst information over trait points `[-2, 0, 2]` by `15.789%` and reducing
  worst conditional standard error from `0.890897` to `0.827931`.
- Bock, R. D., & Mislevy, R. J. (1982). Adaptive EAP estimation of ability in
  a microcomputer environment. *Applied Psychological Measurement, 6*(4),
  431–444. https://doi.org/10.1177/014662168200600405
- Hau, K.-T., & Chang, H.-H. (2001). Item selection in computerized adaptive
  testing: Should more discriminating items be used first? *Journal of
  Educational Measurement, 38*(3), 249–266.
  https://doi.org/10.1111/j.1745-3984.2001.tb01126.x
  These ground the released EAP scoring and maximum-information item-selection
  path reused by source `f4513527`. Across 400 known synthetic candidate
  deployments, adaptive selection reaches target SE 0.5 in 7.1775 queries on
  average versus 10.47 for a seeded random order, while reducing theta RMSE
  from 0.607152 to 0.575996 and unobserved-probability MSE from 0.014746 to
  0.007504. Paired 95% intervals are `[-3.4125, -3.18]` queries,
  `[-0.080874, 0.006129]` theta squared error, and
  `[-0.008804, -0.005716]` unobserved-probability squared error. The theta
  interval includes zero, so that accuracy improvement is not established.
  This one-dimensional onboarding screen neither identifies an invariant model
  ability nor measures live per-request decision latency.
- Luo, X., Kim, D., & Dickison, P. (2018). Projection-based stopping rules for
  computerized adaptive testing in licensure testing. *Applied Psychological
  Measurement, 42*(4), 275–290.
  https://doi.org/10.1177/0146621617726790
  Grounds distinguishing classification-oriented confidence-interval stopping
  from a uniform score-precision target. Source `f4cceb59` stops when the 95%
  normal interval excludes a declared zero cut or at 12 queries. Across 400
  known synthetic candidates it averages 9.875 queries, stops early for 41%,
  and exactly matches the fixed-length decisions and 0.9125 accuracy; the
  paired query-delta interval is `[-2.425, -1.835]` and the accuracy-delta
  interval is `[0, 0]`. Near-cut behavior, normal-interval calibration, buyer
  decision costs, and live query latency remain unvalidated.
  Source `298e1fc8` makes the known near-cut limitation observable: candidates
  within 0.5 of the cut stop early 3% of the time, average 11.86 queries, and
  reach 0.70 accuracy; candidates at least 1.0 away stop early 68%, average
  8.305 queries, and reach 1.0 accuracy. These descriptive synthetic strata
  are complemented by source `e2cb547f`: 42.5% are confidence-resolved with
  1.0 conditional synthetic accuracy, but near-cut resolution is only 3%.
  These are not calibrated subgroup guarantees.
- Chow, C. K. (1970). On optimum recognition error and reject tradeoff. *IEEE
  Transactions on Information Theory, 16*(1), 41–46.
  https://doi.org/10.1109/TIT.1970.1054406
  Establishes the error–reject tradeoff rather than treating forced coverage as
  free. Redistribution permission was not established, so this repository
  records the citation and decision impact instead of copying the PDF.
- El-Yaniv, R., & Wiener, Y. (2010). On the foundations of noise-free selective
  classification. *Journal of Machine Learning Research, 11*, 1605–1641.
  https://www.jmlr.org/papers/v11/el-yaniv10a.html
  Grounds risk–coverage evaluation for classification with a reject option.
  Source `e1ff2e61` selects `z=1.645` on a development seed under a 2.5% Wilson
  error-upper-bound rule. Against `z=1.96` on the same independent responses,
  coverage rises from 44.25% to 56% and all-candidate mean queries fall from
  9.88 to 8.395; paired intervals are `[8.75, 14.75]` percentage points and
  `[-1.715, -1.2625]`. Observed selective risk is zero with a 1.686% Wilson
  upper bound; buyer costs and live coverage remain unexecuted.
  Source `609faff8` repeats the comparison across ten independent response
  seeds. Efficiency gains persist, but the 2.5% Wilson error ceiling passes in
  only 20% of runs and the worst upper bound is 4.540%; the candidate threshold
  is therefore rejected rather than promoted from a favorable single holdout.
- Morris, T. P., White, I. R., & Crowther, M. J. (2019). Using simulation
  studies to evaluate statistical methods. *Statistics in Medicine, 38*(11),
  2074–2102. https://doi.org/10.1002/sim.8086
  Grounds ADEMP planning and reporting Monte Carlo standard errors. Source
  `1862893a` reports MCSE 0.1265 for the ten-run ceiling-pass rate and 0.00619,
  0.02257, and 0.00211 for coverage delta, query delta, and selective risk. A
  worst-case binomial design needs 400 replications for target MCSE 0.025, so
  the current audit rejects admission but does not claim a precise pass rate.
- Chen, W.-H., & Thissen, D. (1997). Local dependence indexes for item pairs
  using item response theory. *Journal of Educational and Behavioral
  Statistics, 22*(3), 265–289.
  https://doi.org/10.3102/10769986022003265
  Grounds pairwise signed X2/G2 diagnostics for dichotomous responses. The
  Rust implementation already exists in `fast-mlsirm`; owner PR #1748 exposes
  it to Python without inventing a universal cutoff. CO adoption still requires
  a preregistered buyer matrix, multiplicity plan, and decision threshold.
- Debeer, D., & Janssen, R. (2013). Modeling item-position effects within an
  IRT framework. *Journal of Educational Measurement, 50*(2), 164–185.
  https://doi.org/10.1111/jedm.12009
  Grounds a limited explanatory-IRT adaptation: the released `fast-mlsirm`
  multigroup item-covariate path can estimate one preregistered item-side
  language/domain difficulty contrast. It does not estimate language-specific
  discrimination or residual effects, and cannot pass without linked buyer
  observations and anchors.
- Doebler, A. (2012). The problem of bias in person parameter estimation in
  adaptive testing. *Applied Psychological Measurement, 36*(4), 255–270.
  https://doi.org/10.1177/0146621612443304
  Shows that item-calibration error and unmodeled testlet/item-generation effects
  can systematically bias adaptive estimates even when calibration errors are
  unbiased. Routing therefore cannot treat adaptively observed cells as a dense,
  ignorable sample.
- Finkelman, M., Nering, M. L., & Roussos, L. A. (2009). A conditional exposure
  control method for multidimensional adaptive testing. *Journal of Educational
  Measurement, 46*(1), 84–103.
  https://doi.org/10.1111/j.1745-3984.2009.01070.x
  Grounds explicit randomized exposure control. CO must record the actual
  selection design/probability before any propensity correction; deterministic
  winner-only history is not sufficient evidence. Source commit `46e15555`
  now records the candidate set, attempts, selection, and policy identity while
  honestly leaving deterministic propensity unidentified. Source commit
  `36dbf3bb` quantifies the consequence in the preregistered synthetic design:
  winner-only candidate means have RMSE `0.321979` against known truth, while
  logged inverse-propensity estimates have RMSE `0.008943`, a `0.313036`
  reduction. This is an estimator contract, not buyer evidence.
- Barrada, J. R., Olea, J., & Ponsoda, V. (2007). Methods for restricting
  maximum exposure rate in computerized adaptive testing. *Methodology, 3*(1),
  14–23. https://doi.org/10.1027/1614-2241.3.1.14
  Grounds the released `fast-mlsirm` CAT exposure-control surface. Selection
  and administration probabilities used to limit item exposure are not logged
  gateway routing propensities and do not identify outcomes for candidates the
  gateway did not call.
- Horvitz, D. G., & Thompson, D. J. (1952). A generalization of sampling
  without replacement from a finite universe. *Journal of the American
  Statistical Association, 47*(260), 663–685.
  https://doi.org/10.1080/01621459.1952.10483446
  Grounds inverse-probability weighting when inclusion probabilities are known.
- Dudík, M., Langford, J., & Li, L. (2011). Doubly robust policy evaluation and
  learning. In *Proceedings of ICML 2011* (pp. 1097–1104).
  https://arxiv.org/abs/1103.4601
  Shows why partial-feedback policy evaluation needs the logging policy or a
  reward model and why inverse propensity alone can have high variance.
- Swaminathan, A., & Joachims, T. (2015). Batch learning from logged bandit
  feedback through counterfactual risk minimization. *JMLR, 16*(52), 1731–1755.
  https://jmlr.org/papers/v16/swaminathan15a.html
  Grounds propensity-weighted risk with an explicit variance penalty. Source
  commit `2c783b98` adds only the prerequisite fixed-seed logging-policy test;
  production learning and buyer evidence remain out of scope until gated.
- Stocking, M. L., & Lord, F. M. (1983). Developing a common metric in item
  response theory. *Applied Psychological Measurement, 7*(2), 201–210.
  https://doi.org/10.1177/014662168300700208
  Grounds characteristic-curve linking across separately calibrated forms.
  Source commit `ca6e9a75` recovers a known six-anchor affine transform with
  true-parameter RMSE `3.24e-16`; buyer anchors remain unexecuted.
- Swaminathan, H., & Rogers, H. J. (1990). Detecting differential item
  functioning using logistic regression procedures. *Journal of Educational
  Measurement, 27*(4), 361–370.
  https://doi.org/10.1111/j.1745-3984.1990.tb00754.x
  Grounds the requirement to distinguish uniform and nonuniform DIF after
  conditioning on the measured trait. The current synthetic routing surface has
  neither buyer groups nor an anchored matching variable, so it reports
  `measurement_validity=false` instead of fabricating a DIF result.
- French, B. F., & Maller, S. J. (2007). Iterative purification and effect size
  use with logistic regression for differential item functioning detection.
  *Educational and Psychological Measurement, 67*(3), 373–393.
  https://doi.org/10.1177/0013164406294781
  Together these ground logistic DIF and iterative removal of contaminated
  matching items. Source commit `d0d81e8f` detects the single injected cohort
  shift with recall 1.0 and zero false positives after purification.
- Linacre, J. M. (1989). *Many-facet Rasch measurement*. MESA Press.
- Eckes, T. (2015). *Introduction to many-facet Rasch measurement* (2nd ed.).
  Peter Lang. https://doi.org/10.3726/978-3-653-04844-5
- Bock, R. D., & Aitkin, M. (1981). Marginal maximum likelihood estimation of
  item parameters: Application of an EM algorithm. *Psychometrika, 46*(4),
  443–459. https://doi.org/10.1007/BF02293801
  These ground the judge facet and its marginal-ML estimation. Source commit
  `ac28b6d0` recovers centered judge severity with RMSE 0.018292 in a connected
  synthetic design; buyer judge identities and ratings remain unexecuted.
- He, Y., & Qi, Y. (2023). Using response time in multidimensional
  computerized adaptive testing. *Journal of Educational Measurement, 60*(4),
  697–738. https://doi.org/10.1111/jedm.12373
  Grounds a joint accuracy-time KPI: maximize information per unit time rather
  than treating latency as a tie-breaker after accuracy.
- Nadaraya, E. A. (1964). On estimating regression. *Theory of Probability &
  Its Applications, 9*(1), 141–142. https://doi.org/10.1137/1109020
  Grounds local similarity-weighted probability interpolation. The gateway
  uses the smallest bounded form: two positive-cosine neighbors, with no
  learned bandwidth or claim of reproducing the paper's estimator.

The current gateway does not claim these papers' full estimators. Candidate changes
must report held-out prediction quality or true-parameter RMSE together with
route-decision latency; faster Python preparation alone is a latency result,
not an accuracy improvement. Production evidence must identify the measured
unit as a versioned endpoint + model + system/decode/tool policy, preserve
anchor interactions across recalibration, report uncertainty and subgroup/domain
DIF, and log randomized exposure or propensities when routing controls which
responses are observed. Without those conditions, the safe result is "no
psychometric evidence", never a portable ability rank.

- Lior, G., Frostig, T., Stanovsky, G., & Eyal, M. (2026). *Extending item
  response theory for efficient and meaningful multilingual evaluation*
  [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2606.15643
  Grounds a safer multilingual extension: language is modeled with explicit
  difficulty deviations, language/content discrimination components, and
  language-specific residuals rather than being forced into a person-group DIF
  variable. Its reported predictive gains do not establish invariance for this
  gateway; buyer-language replication and anchor continuity remain required.

## Evaluation methodology (NIM cost-quality benchmark)

- **Holistic Evaluation of Language Models (HELM)** — Percy Liang, Rishi
  Bommasani, Tony Lee, et al. arXiv:2211.09110, 2022 (TMLR 2023).
  `helm-holistic-evaluation-2211.09110.pdf`
  Grounds the **NIM benchmark harness** (`docs/nim_benchmark.md`): evaluate a
  broad, explicitly enumerated model pool on multiple metrics at once (quality,
  latency, cost) instead of a single leaderboard number; report incompleteness
  honestly (skipped/unsupported/rate-limited cells stay machine-readable rather
  than silently dropped); and standardize conditions across compared systems
  (same tasks, scorers, caps, and budgets). Distributed under the arXiv
non-exclusive license / CC BY as marked on arXiv.

## Repository-wide referenced research

The following papers ground implementation or architecture elsewhere in this
repository. This register deliberately excludes RFC, NIST, ISO, OWASP, and
vendor documentation; those remain standards or product sources rather than
academic papers. `tests/test_paper_contracts.py` normalizes arXiv URLs and DOI
forms and fails when a scholarly identifier used by tracked Python or Markdown
is absent here.

- Bradley, R. A., & Terry, M. E. (1952). Rank analysis of incomplete block
  designs: I. The method of paired comparisons. *Biometrika, 39*(3/4), 324–345.
  https://doi.org/10.1093/biomet/39.3-4.324
- Chiang, W.-L., Zheng, L., Sheng, Y., Angelopoulos, A. N., Li, T., Li, D.,
  Zhang, H., Zhu, B., Jordan, M. I., Gonzalez, J. E., & Stoica, I. (2024).
  *Chatbot Arena: An open platform for evaluating LLMs by human preference*
  [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2403.04132
- Li, H., Zhang, Q., Wu, Y., Xiao, X., Li, Z., Xia, S.-T., & Liu, H. (2025).
  *Evaluating scoring bias in LLM-as-a-judge* [Preprint]. arXiv.
  https://arxiv.org/abs/2506.22316
- Zheng, C., Zhou, H., Meng, F., Zhou, J., & Huang, M. (2024). Large language
  models are not robust multiple choice selectors. *International Conference
  on Learning Representations*.
  https://proceedings.iclr.cc/paper_files/paper/2024/hash/54dd9e0cff6d9214e20d97eb2a3bae49-Abstract-Conference.html
- Pezeshkpour, P., & Hruschka, E. (2024). Large language models sensitivity to
  the order of options in multiple-choice questions. In *Findings of the
  Association for Computational Linguistics: NAACL 2024* (pp. 2006–2017).
  https://aclanthology.org/2024.findings-naacl.130/
- Sharma, M., Tong, M., Korbak, T., Duvenaud, D., Askell, A., Bowman, S. R.,
  Cheng, N., Durmus, E., Hatfield-Dodds, Z., Johnston, S. R., Kravec, S.,
  Maxwell, T., McCandlish, S., Ndousse, K., Rausch, O., Schiefer, N., Yan, D.,
  Zhang, M., & Perez, E. (2023). *Towards understanding sycophancy in language
  models* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2310.13548
  Research page:
  https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models
- Ma, H., Lai, G., & Ye, H.-J. (2026). *MMR-Bench: A comprehensive benchmark
  for multimodal LLM routing* [Preprint]. arXiv.
  https://doi.org/10.48550/arXiv.2601.17814
- Jeon, M., Jin, I. H., Schweinberger, M., & Baugh, S. (2021). Mapping
  unobserved item–respondent interactions: A latent space item response model
  with interaction map. *Psychometrika, 86*(2), 378–403.
  https://doi.org/10.1007/s11336-021-09762-5
- Iannario, M., Monti, A. C., & Scalera, P. (2022). The number of response
  categories in ordered response models. *The International Journal of
  Biostatistics, 18*(2), 593–611.
  https://doi.org/10.1515/ijb-2021-0013
- Jones, W. P., & Loe, S. A. (2013). Optimal number of questionnaire response
  categories. *SAGE Open, 3*(2).
  https://doi.org/10.1177/2158244013489691
- Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., Lin,
  Z., Li, Z., Li, D., Xing, E., Zhang, H., Gonzalez, J. E., & Stoica, I.
  (2023). *Judging LLM-as-a-judge with MT-Bench and Chatbot Arena* [Preprint].
  arXiv. https://arxiv.org/abs/2306.05685
- Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D.,
  & Yih, W.-t. (2020). Dense passage retrieval for open-domain question
  answering. In *Proceedings of EMNLP 2020* (pp. 6769–6781).
  https://doi.org/10.18653/v1/2020.emnlp-main.550
- Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM Computer
  Communication Review, 18*(4), 314–329. https://doi.org/10.1145/52325.52356
- Dean, J., & Barroso, L. A. (2013). The tail at scale. *Communications of the
  ACM, 56*(2), 74–80. https://doi.org/10.1145/2408776.2408794
- Gardner, K., Harchol-Balter, M., Scheller-Wolf, A., & Van Houdt, B. (2017).
  Redundancy-d: The power of d choices for redundancy. *Operations Research,
  65*(4), 1078–1094. https://doi.org/10.1287/opre.2016.1582
- Codd, E. F. (1970). A relational model of data for large shared data banks.
  *Communications of the ACM, 13*(6), 377–387.
  https://doi.org/10.1145/362384.362685
- Birrell, A. D., & Nelson, B. J. (1984). Implementing remote procedure calls.
  *ACM Transactions on Computer Systems, 2*(1), 39–59.
  https://doi.org/10.1145/2080.357392
- Garcia-Molina, H., & Salem, K. (1987). Sagas. In *Proceedings of ACM SIGMOD*
  (pp. 249–259). https://doi.org/10.1145/38713.38742
- Yang, N., Barringer, H., & Zhang, N. (2007). A purpose-based access control
  model. In *Proceedings of IAS 2007*. IEEE.
  https://doi.org/10.1109/IAS.2007.29
- Popa, R. A., Redfield, C. M. S., Zeldovich, N., & Balakrishnan, H. (2011).
  CryptDB: Protecting confidentiality with encrypted query processing. In
  *Proceedings of the 23rd ACM Symposium on Operating Systems Principles*
  (pp. 85–100). https://doi.org/10.1145/2043556.2043566
- Wolf, K., Pallas, F., & Tai, S. (2021). *Messaging with purpose limitation:
  Privacy-compliant publish-subscribe systems* [Preprint]. arXiv.
  https://arxiv.org/abs/2110.15150

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, including
PagedAttention / vLLM (2309.06180) and DeepSpeed-FastGen (2401.08671), which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.

## APA 7th edition references

Chen, L., Zaharia, M., & Zou, J. (2023). FrugalGPT: How to use large language
models while reducing cost and improving performance. *arXiv*.
https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan,
L. V. S., & Awadallah, A. H. (2024). Hybrid LLM: Cost-efficient and
quality-aware query routing. *arXiv*.
https://doi.org/10.48550/arXiv.2404.14618

Liang, P., Bommasani, R., Lee, T., Tsipras, D., Soylu, D., Yasunaga, M., Zhang,
Y., Narayanan, D., Wu, Y., Kumar, A., Newman, B., Yuan, B., Yan, B., Zhang, C.,
Cosgrove, C., Manning, C. D., Ré, C., Acosta-Navas, D., Hudson, D. A., … Koreeda,
Y. (2023). Holistic evaluation of language models. *Transactions on Machine
Learning Research*. https://doi.org/10.48550/arXiv.2211.09110

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). RouteLLM: Learning to route LLMs with preference
data. *arXiv*. https://doi.org/10.48550/arXiv.2406.18665

He, Y., & Qi, Y. (2023). Using response time in multidimensional computerized
adaptive testing. *Journal of Educational Measurement, 60*(4), 697–738.
https://doi.org/10.1111/jedm.12373

Song, W., Huang, Z., Cheng, C., Gao, W., Xu, B., Zhao, G., Wang, F., & Wu, R.
(2025). *IRT-Router: Effective and interpretable multi-LLM routing via item
response theory* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2506.01048

Nadaraya, E. A. (1964). On estimating regression. *Theory of Probability &
Its Applications, 9*(1), 141–142. https://doi.org/10.1137/1109020
