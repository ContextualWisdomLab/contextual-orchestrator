# Papers grounding the cost-review + routing hub

These papers ground the design of the LLM **cost review** ledger and the
**sync-vs-batch / upstream** routing added in `feat/cost-review-and-batch-routing`.
References below include arXiv preprints and other publications. Redistribution
must be verified for the exact version of each PDF: arXiv's perpetual,
non-exclusive license grants distribution rights to arXiv, not a blanket
permission for this repository to redistribute it. See the
[arXiv license guidance](https://info.arxiv.org/help/license/index.html).
Version-page licenses are recorded below. Additional redistribution permission,
where required, and the contents of release archives remain unverified.

## Stored PDF version inventory

First-page text inspection on 2026-09-09 identifies the following versions.
This establishes document identity, not redistribution permission or a complete
research review. License verification must use these versions, not whichever
version the unversioned abstract page currently serves.

| Stored paper | Embedded arXiv version | Embedded date |
| --- | --- | --- |
| FrugalGPT | 2305.05176v1 | 2023-05-09 |
| RouteLLM | 2406.18665v4 | 2025-02-23 |
| Hybrid LLM | 2404.14618v1 | 2024-04-22 |
| HELM | 2211.09110v2 | 2023-10-01 |
| The Art, Science, and Engineering of Fuzzing: A Survey | 1812.00140v4 | 2019-04-08 |

Version-specific arXiv abstract pages were checked on 2026-09-09:

| Version page | Declared license | Release implication |
| --- | --- | --- |
| [2305.05176v1](https://arxiv.org/abs/2305.05176v1) | arXiv nonexclusive-distrib/1.0 | Additional redistribution basis not established. |
| [2406.18665v4](https://arxiv.org/abs/2406.18665v4) | arXiv nonexclusive-distrib/1.0 | Additional redistribution basis not established. |
| [2404.14618v1](https://arxiv.org/abs/2404.14618v1) | CC BY-NC-ND 4.0 | Do not assume commercial redistribution rights. |
| [2211.09110v2](https://arxiv.org/abs/2211.09110v2) | CC BY 4.0 | Preserve attribution and license requirements. |
| [1812.00140v4](https://arxiv.org/abs/1812.00140v4) | arXiv nonexclusive-distrib/1.0 | Additional redistribution basis not established. |

This checks the declared version-page licenses. The local bytes were hashed on
2026-09-09 in [stored_pdf_sha256.txt](stored_pdf_sha256.txt); from the repository
root run `shasum -a 256 -c docs/papers/stored_pdf_sha256.txt` to verify all five.
These hashes identify the stored copies only: comparison with publisher bytes,
redistribution permission, and release-package inclusion remain separate checks.
Existing files are retained during the audit.

At source commit `15b8f52b`, `uv build` produced both package formats and
archive-member inspection found no `.pdf` members in either:

- `contextual_orchestrator-0.2.0-py3-none-any.whl`, SHA-256
  `9091060d05ee07fa52e48918195c9e14388d6d9e85182b7919fcdf3f5db6e152`.
- `contextual_orchestrator-0.2.0.tar.gz`, SHA-256
  `75747f6a0a841046bdad44f5edc408f81839fa8c53b09efa2c2e5710c4c6d180`.

These are local build artifacts, not published-package evidence. Git source
archives include tracked PDFs and require a separate redistribution decision.

## Cost optimisation

- **FrugalGPT: How to Use Large Language Models While Reducing Cost and
  Improving Performance** — Lingjiao Chen, Matei Zaharia, James Zou. arXiv:2305.05176, 2023.
  `frugalgpt-cost-2305.05176.pdf`
  Motivates the **configurable price table + per-request cost accounting** and
  cost-optimising model selection: cost varies by orders of magnitude across
  providers/models, so a gateway should price each request and route to the
  cheapest capable upstream. Version-page license: arXiv non-exclusive;
  additional redistribution basis unverified.
  source: https://arxiv.org/abs/2305.05176.

## Query routing (which upstream / which tier)

- Song et al. (2025), *IRT-Router: Effective and interpretable multi-LLM routing
  via item response theory*, https://doi.org/10.18653/v1/2025.acl-long.761.
  See the [measurement review](../doctoring/irt_router_measurement_review.md)
  for page-level visual inspection and the distinction between prediction fit
  and identified psychometric interpretation. Citation only; no PDF vendored.

- **RouteLLM: Learning to Route LLMs with Preference Data** — Isaac Ong, Amjad
  Almahairi, Vincent Wu, Wei-Lin Chiang, Tianhao Wu, Joseph E. Gonzalez, M.
  Waleed Kadous, Ion Stoica. arXiv:2406.18665, 2024.
  `routellm-routing-2406.18665.pdf`
  Grounds the **routing decision** layer (`RoutingPolicy` + cost-aware upstream
  selection): route strong/weak model choices to hit a cost/quality target.
  Version-page license: arXiv non-exclusive; additional redistribution basis
  unverified. Source: https://arxiv.org/abs/2406.18665.

- **Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing** — Dujian Ding,
  Ankur Mallick, Chi Wang, Robert Sim, Subhabrata Mukherjee, Victor Rühle,
  Laks V. S. Lakshmanan, Ahmed Hassan Awadallah. arXiv:2404.14618 (ICLR 2024).
  `hybrid-llm-query-routing-2404.14618.pdf`
  Supports selecting between small and large models using predicted response
  quality differences and a configurable quality target. It does not establish
  this repository's sync/batch transport policy or equate bulk requests with
  easy items. Those are separate product decisions requiring their own evidence.
  Version-page license: CC BY-NC-ND 4.0;
  source: https://arxiv.org/abs/2404.14618.

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

`run_equal_budget_ablation` emits estimated, synthetic true-parameter evidence
for unit-test recovery checks. It does not establish buyer accuracy or authorize
live routing changes. A Boolean returned by `production_default_change_allowed`
is not sufficient deployment evidence: caller-declared measurement status and
robustness do not authenticate observed outcomes. The repair tracked in
[PR #1074](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1074)
remains proposed until protected integration. Live defaults require independently
verified observed-task evidence and the protected release process.

## Evaluation methodology (NIM cost-quality benchmark)

- Chiang, W.-L., Zheng, L., Sheng, Y., Angelopoulos, A. N., Li, T., Li, D.,
  Zhang, H., Zhu, B., Jordan, M. I., Gonzalez, J. E., & Stoica, I. (2024).
  *Chatbot Arena: An open platform for evaluating LLMs by human preference*.
  arXiv. https://doi.org/10.48550/arXiv.2403.04132
  Cited by `contextual_orchestrator/benchmark_priors.py`. Version 1 metadata
  and HTML sections 3–4 were inspected on 2026-09-09. Pairwise human preference
  is distinct from absolute task correctness. The repository's equal-weight
  composite of normalized Arena and Quality Index scores is not validated by
  this citation; its historical snapshot values also need archived provenance.
  Citation only; no PDF copied. This is not a completed full-paper review.

- **Holistic Evaluation of Language Models (HELM)** — Percy Liang, Rishi
  Bommasani, Tony Lee, et al. arXiv:2211.09110, 2022 (TMLR 2023).
  `helm-holistic-evaluation-2211.09110.pdf`
  Grounds the **NIM benchmark harness** (`docs/nim_benchmark.md`): evaluate a
  broad, explicitly enumerated model pool on multiple metrics at once (quality,
  latency, cost) instead of a single leaderboard number; report incompleteness
  honestly (skipped/unsupported/rate-limited cells stay machine-readable rather
  than silently dropped); and standardize conditions across compared systems
  (same tasks, scorers, caps, and budgets). Version-page license: CC BY 4.0;
  source: https://arxiv.org/abs/2211.09110.

## Psychometrics beyond orchestration

### Cross-document reference index

At `fcf0047c37706975d9bff1ab4b95c54a2a383f54`, a tracked-text census found
six explicit arXiv identifiers referenced elsewhere but absent from this index.
Their existing evidence records remain canonical; these links do not imply
that the papers were fully reviewed, their claims reproduced, or PDFs licensed.

| Identifier | Existing evidence and implementation discussion |
| --- | --- |
| 1810.07876 | [Measured routing evidence](../doctoring/measured-routing-evidence.md) |
| 2007.08719 | [Measured routing evidence](../doctoring/measured-routing-evidence.md) |
| 2306.05685 | [Measured routing evidence](../doctoring/measured-routing-evidence.md) |
| 2506.22316 | [Polytomous judge benchmark](../benchmarks/2026-08-11-polytomous-llm-judge.md) and [judge calibration ADR](../planning/adrs/0006-polytomous-llm-judge-bias-calibration.md) |
| 2110.15150 | [Purpose-limited protection ADR](../planning/adrs/0028-purpose-limited-pii-protection.md) |
| 2601.17814 | [Model-group specification](../model-group-product-technical-spec.md) and [free-pool admission research](../research/review-gateway-free-pool-admission.md) |

Scope: explicit arXiv URL, colon, and DOI-style identifiers in tracked Python,
Rust, Markdown, and TOML files. This is a discovery census, not a complete
bibliography: DOI-only sources, author/year citations, other formats, and
references inside PDFs need separate reconciliation. The table includes
non-psychometric references to avoid hiding cross-cutting dependencies.

### Interpretation constraints

Additional DOI-only lead: Kang and Jeon (2025),
[Multidimensional latent space item response models](https://doi.org/10.1017/psy.2025.5).
The [bounded read and reproduction receipt](../doctoring/measured-routing-evidence.md)
records the abstract/model scope and a directly viewed supplementary-code name
mismatch. This extends discovery beyond the arXiv census; it does not establish
a completed reproduction or a released fast-mlsirm implementation.

These sources constrain what a routing score may mean; they are not routing
algorithms. They add validity, identification, and fair-comparison checks:

- Messick (1995) frames validity as an argument about score interpretation and
  use. Buyer-facing quality claims therefore need a construct, intended use,
  observed outcome, and limitation record; a judge label alone is insufficient.
- Embretson and Reise (2000) describe item information and identifiability in
  IRT. Select extra items or raters by expected information only after scale
  alignment and exposure limits are declared; never optimize a raw judge score
  as if it were theta.
- Reise, Ainsworth, and Haviland (2005) separate fit, parameter interpretation,
  and practical measurement. Report family-wise fit and uncertainty separately
  from route accuracy and latency, and fail closed when identification is absent.
- Kim and Chung (2019) examine expanded test use using item DIF and subgroup
  linking invariance. Their methods distinguish item-level behavior from
  score-level comparability. Read scope: abstract and printed pages 1–8, not a
  complete review of results. The [implementation proposal](../doctoring/autonomous_kpi_runbook.md#expanded-population-validity-proposal)
  is an engineering inference, not a demonstrated LLM-routing result.

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, including
PagedAttention / vLLM (2309.06180) and DeepSpeed-FastGen (2401.08671), which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

> Citations provide attribution, not redistribution permission. Apply the
> version-specific inventory above before including PDFs in a release; the
> arXiv non-exclusive license alone does not authorize this repository's reuse.

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

Embretson, S. E., & Reise, S. P. (2000). *Item response theory for
psychologists*. Lawrence Erlbaum Associates.

Messick, S. (1995). Validity of psychological assessment: Validation of
inferences from persons' responses and performances as scientific inquiry into
score meaning. *American Psychologist, 50*(9), 741–749.
https://doi.org/10.1037/0003-066X.50.9.741

Reise, S. P., Ainsworth, A. T., & Haviland, M. G. (2005). Item response theory:
Fundamentals, applications, and promise in psychological research. *Current
Opinion in Psychiatry, 18*(5), 611–616.
https://doi.org/10.1097/01.yco.0000170421.57227.9b

Kim, S., & Chung, S. (2019). *Psychometric evidence to assess expanded test
use* (Research Memorandum No. RM-19-07). Educational Testing Service.
https://www.ets.org/Media/Research/pdf/RM-19-07.pdf

The report states all rights reserved. Link and citation only; no PDF vendored.
## DOI discovery register

The links below are explicit citations found in tracked source and documentation,
not newly reviewed papers or verified implementation evidence. Some identify
standards rather than papers. Existing citation discussions remain authoritative;
this register prevents DOI-only sources from escaping the discovery inventory.
Case and sentence-final punctuation are normalized by the inventory test.

- [DOI 10.1007/s11336-006-1478-z](https://doi.org/10.1007/s11336-006-1478-z)
- [DOI 10.1007/s11336-021-09762-5](https://doi.org/10.1007/s11336-021-09762-5)
- [DOI 10.1017/psy.2025.5](https://doi.org/10.1017/psy.2025.5)
- [DOI 10.1037/0003-066X.50.9.741](https://doi.org/10.1037/0003-066X.50.9.741)
- [DOI 10.1093/biomet/39.3-4.324](https://doi.org/10.1093/biomet/39.3-4.324)
- [DOI 10.1097/01.yco.0000170421.57227.9b](https://doi.org/10.1097/01.yco.0000170421.57227.9b)
- [DOI 10.1109/IAS.2007.29](https://doi.org/10.1109/IAS.2007.29)
- [DOI 10.1111/rssc.12569](https://doi.org/10.1111/rssc.12569)
- [DOI 10.1145/2043556.2043566](https://doi.org/10.1145/2043556.2043566)
- [DOI 10.1145/2080.357392](https://doi.org/10.1145/2080.357392)
- [DOI 10.1145/2408776.2408794](https://doi.org/10.1145/2408776.2408794)
- [DOI 10.1145/362384.362685](https://doi.org/10.1145/362384.362685)
- [DOI 10.1145/38713.38742](https://doi.org/10.1145/38713.38742)
- [DOI 10.1145/52325.52356](https://doi.org/10.1145/52325.52356)
- [DOI 10.1287/opre.2016.1582](https://doi.org/10.1287/opre.2016.1582)
- [RFC 4193](https://doi.org/10.17487/RFC4193)
- [RFC 6265](https://doi.org/10.17487/RFC6265)
- [RFC 6598](https://doi.org/10.17487/RFC6598)
- [RFC 9110](https://doi.org/10.17487/RFC9110)
- [DOI 10.18653/v1/2020.emnlp-main.550](https://doi.org/10.18653/v1/2020.emnlp-main.550)
- [DOI 10.18653/v1/2025.acl-long.761](https://doi.org/10.18653/v1/2025.acl-long.761)
- [arXiv 2211.09110 DOI](https://doi.org/10.48550/arXiv.2211.09110)
- [arXiv 2305.05176 DOI](https://doi.org/10.48550/arXiv.2305.05176)
- [arXiv 2403.04132 DOI](https://doi.org/10.48550/arXiv.2403.04132)
- [arXiv 2404.14618 DOI](https://doi.org/10.48550/arXiv.2404.14618)
- [arXiv 2406.18665 DOI](https://doi.org/10.48550/arXiv.2406.18665)
- [arXiv 2512.04388 DOI](https://doi.org/10.48550/arXiv.2512.04388)
- [arXiv 2512.04695 DOI](https://doi.org/10.48550/arXiv.2512.04695)
- [arXiv 2601.17814 DOI](https://doi.org/10.48550/arXiv.2601.17814)
- [NIST AI 100-1](https://doi.org/10.6028/NIST.AI.100-1)
- [NIST AI 600-1](https://doi.org/10.6028/NIST.AI.600-1)
- [NIST SP 800-204](https://doi.org/10.6028/NIST.SP.800-204)
- [NIST SP 800-207](https://doi.org/10.6028/NIST.SP.800-207)
- [NIST SP 800-53r5](https://doi.org/10.6028/NIST.SP.800-53r5)
- [NIST SP 800-57pt1r5](https://doi.org/10.6028/NIST.SP.800-57pt1r5)
- [NIST SP 800-63b](https://doi.org/10.6028/NIST.SP.800-63b)
- [NIST SP 800-92](https://doi.org/10.6028/NIST.SP.800-92)
