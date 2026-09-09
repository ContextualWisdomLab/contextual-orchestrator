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
| Laplace rule of succession as stability prior | Beta(1,1) is an explicit uniform prior for Bernoulli probability, not a uniquely assumption-free choice (Gelman et al., 2013). Calibration and sensitivity to the prior require separate evidence. | Stability tests assert alpha/(alpha+beta) exactly; arithmetic correctness is not calibration evidence. |
| Cosine similarity over declared metadata documents | Dense retrieval established query-document cosine ordering without keyword overlap (Karpukhin et al., 2020). Affinity uses operator-declared descriptors only. | Deterministic mock-embedding tests verify cosine ordering and zero-vector guards. |
| Strict JSON triage verdict | The schema is a CO boundary-validation decision. Zheng et al. (2023) examine judge agreement and biases; their citation does not establish that this schema makes a verdict correct. | Parser tests reject seven malformed-reply classes and cache verdicts by content hash; these checks do not measure human agreement. |
| Real-time judging before returning answers | RouteLLM/FrugalGPT motivate quality-aware routing between models (Ong et al., 2024; Chen et al., 2023); here quality is measured per deployment instead of trained offline. | Judge-driven failover tests prove rejection routes to the next candidate within budget while updating both ledgers. |
| Per-member quality ledger; latent-interaction research candidate | Jeon et al. (2021) model latent item–respondent interactions. Separate per-member Beta posteriors do not implement that model, establish multilevel validity, or justify group-level inference from individual results. | Quality-ledger reports expose per-member posteriors consumed by `_measured_member_order`; interaction recovery and cross-group validity remain separate acceptance work. |

### Citation correction, 2026-09-09

Audit source: `279f7e03`, before this correction. The Jeon et al. entry previously
used an incorrect title and DOI. The authors' [arXiv record, version 3](https://arxiv.org/abs/2007.08719v3)
identifies the latent-space paper and links its published DOI. This corrects the
reference, not evidence that CO implements the cited estimator. The former
claims that separate ledgers prevent atomistic fallacy and that JSON structure
establishes judge reliability are withdrawn. No runtime behavior or score
formula changes in this correction. Current calibration, sampling design, and
group/time validity must be measured before interpreting ledger scores as
psychometric accuracy.

### Hybrid LLM attribution correction, 2026-09-09

Reviewed the authors' [version-one text](https://arxiv.org/html/2404.14618v1),
especially Sections 2–3. Model choice based on predicted quality gaps does not
establish sync/batch transport choice. Removed that attribution from the paper
index; no runtime policy changed. In psychometric work, request urgency and
batchability must not become unvalidated proxies for item difficulty. A policy
combining these signals needs separately identified constructs and observed
outcome validation. Existing `test_paper_contracts.py` checks role/trace behavior
and citation strings, not faithful paper reproduction or empirical validity.

Section 4.4/Table 2 reports router mean latency 0.036 ± 0.002 seconds over
200 randomly chosen queries; the uncertainty is one standard error, not a
95% interval or p95. The paper explicitly excludes GPT-3.5 API timing because
network, queueing, and inference cannot be separated there. This cannot serve
as CO's 20 ms durable-decision p95 baseline. Section 4.5 selects thresholds on
500 validation examples and evaluates them on a separate test set: retain that
selection/evaluation separation, but do not adopt 500 as a universal sample-size
requirement. CO must choose its sample size from the declared effect, variance,
power, and clustering design. These are interpretation boundaries, not a new
measured performance result or a reproduction of the paper.

## APA 7 references

### Multilevel follow-up source (2026-09-09)

The local Zotero API returned a matching bibliographic record for Jin et al.
(2022); the authors' [arXiv version 5](https://arxiv.org/abs/1810.07876v5)
independently confirms the title and author list. The abstract distinguishes
differences among individual schools from differences between school systems.
This is a relevant methodological lead for preserving task/model/group levels,
not evidence that CO's per-member Beta ledger implements a multilevel model.
Full model review and suitability for gateway data remain open. No participant
data, attachments, private notes, or new Zotero records were copied or created.

Jin, I. H., Jeon, M., Schweinberger, M., Yun, J., & Lin, L. (2022).
Multilevel network item response modelling for discovering differences between
innovation and regular school systems in Korea. *Journal of the Royal
Statistical Society: Series C (Applied Statistics), 71*(5), 1225–1244.
https://doi.org/10.1111/rssc.12569

### LSIRM identification and version discrepancy (2026-09-09)

Read scope: the authors' [arXiv v2 HTML](https://arxiv.org/html/2007.08719v2),
sections 2.1, 2.3.2, 3.2, and 3.3; not the full paper or verified final journal
text. At CO `4e078c5152d7aa021986ffb53735edb6891e1cea`, this extends the
existing Jeon et al. citation without changing an estimator or routing policy.
Section 3.2 identifies translation, reflection, and rotation invariance, uses
Procrustes post-processing, and cautions that interpretation concerns relative
distances rather than absolute positions.

Section 3.3 needs version-level reconciliation before implementation: its
displayed mixture assigns the slab to delta=1, but the following prose selects
Rasch when P(delta=0) is below 0.5 and then describes estimation using delta=1
counts. These event descriptions do not agree. It also describes a spike near
zero for log(gamma); that is not a point mass at gamma=0. This is a discrepancy
in the inspected preprint rendering, not a demonstrated defect in the final
article, supplementary code, or fast-mlsirm. The publisher DOI fetch failed and
the NSF PDF fetch timed out; neither failure establishes source absence.

Engineering consequence: fast-mlsirm owns reconciliation against the final PDF
and supplementary model-selection implementation before publishing such a
contract. CO must not copy this threshold, infer axis meanings, or treat
posterior model selection as held-out customer accuracy. Keep aligned recovery,
observed prediction, and decision latency as separate acceptance measures.

Follow-up: a direct download of the [NSF repository copy](https://par.nsf.gov/servlets/purl/10229440)
succeeded after the browser fetch failures. The 26-page PDF identifies Springer
as creator and carries the journal DOI; SHA-256 is
`587e6967678a639dec5e9824b75baad92e58a042a017c34a837ead45828960a3`.
PDF page 12 was rendered at 1188 × 1600 and directly visually inspected.
The mixture/event discrepancy is also printed there, so it is not solely an
arXiv HTML conversion artifact. This archived Springer-formatted copy is not
yet byte-compared with the current publisher version or supplementary code.
It specifies the spike as N(-3, 1), unlike the generic near-zero description;
do not implement a prior from that description alone. No PDF is vendored.
Local inspection artifacts: `/tmp/lsirm-10229440.pdf` and
`/tmp/lsirm-model-selection.png`; these temporary paths are not release assets.

### Existing references

Kang, I., & Jeon, M. (2025). Multidimensional latent space item response models:
A note on the relativity of conditional dependence. *Psychometrika, 90*(2),
799–826. https://doi.org/10.1017/psy.2025.5

Read receipt (2026-09-09): publisher abstract and model introduction, plus
[supplement S1, pages 1–3](https://static.cambridge.org/content/id/urn%3Acambridge.org%3Aid%3Aarticle%3AS0033312325000055/resource/name/S0033312325000055sup001.pdf).
The paper extends Rasch-based latent-space models with between-item dimensions
and discrimination. Conditional dependence is relative to what the base model
explains. Engineering inference: CO comparison evidence should retain base
formulation and dimensional structure; residual-dependence values from different
models are not automatically interchangeable quality scores.

Direct visual inspection of supplement page 2 (1082 × 1400) confirmed a
declaration of `log_gamma` followed by `lambda = exp(log_lambda)`; S1's extracted
pages 1–3 contain no declaration of `log_lambda`. This is a published-example
name mismatch, not a compiler-run result or evidence against the reported
empirical findings. No Stan execution or Rust port was performed. Reconcile
the executable source before reproduction; fast-mlsirm issue #1713 remains
the candidate-specification owner, not permission to add estimation to CO.

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*. arXiv.
https://arxiv.org/abs/2305.05176

Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., &
Rubin, D. B. (2013). *Bayesian data analysis* (3rd ed.). CRC Press.

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM
Computer Communication Review, 18*(4), 314–329.
https://doi.org/10.1145/52325.52356

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Ruhle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM: Cost-efficient
and quality-aware query routing*. arXiv.
https://doi.org/10.48550/arXiv.2404.14618

Jeon, M., Jin, I. H., Schweinberger, M., & Baugh, S. (2021). Mapping unobserved
item–respondent interactions: A latent space item response model with interaction
map. *Psychometrika, 86*(2), 378–403.
https://doi.org/10.1007/s11336-021-09762-5

Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D.,
& Yih, W.-t. (2020). Dense passage retrieval for open-domain question
answering. In *Proceedings of the 2020 Conference on Empirical Methods in
Natural Language Processing* (pp. 6769–6781). Association for
Computational Linguistics. https://doi.org/10.18653/v1/2020.emnlp-main.550

Laplace, P.-S. (1774). Mémoire sur la probabilité des causes par les
événements. *Mémoires de l'Académie Royale des Sciences de Paris, 6*,
621–656. (Rule of succession; modern treatment in Gelman et al., 2013.)

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs
with preference data*. arXiv. https://arxiv.org/abs/2406.18665

Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., Lin,
Z., Li, Z., Li, D., Xing, E., Zhang, H., Gonzalez, J. E., & Stoica, I.
(2023). *Judging LLM-as-a-judge with MT-Bench and Chatbot Arena*. arXiv.
https://arxiv.org/abs/2306.05685
