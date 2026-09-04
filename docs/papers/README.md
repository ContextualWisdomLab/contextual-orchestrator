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
  honestly leaving deterministic propensity unidentified.
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
- Jeon, M., Jin, I. H., Schweinberger, M., & Baugh, S. (2021). Estimating
  parameters for unidimensional multidimensional logistic item response
  models. *Psychometrika*. https://doi.org/10.1007/s11336-021-09783-y
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
