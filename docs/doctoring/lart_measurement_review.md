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

## Nonlinear dependence: external psychometrics intake

Bolsinova, M., & Molenaar, D. (2018). Modeling nonlinear conditional dependence
between response time and accuracy. *Frontiers in Psychology, 9*, Article 1525.
https://doi.org/10.3389/fpsyg.2018.01525

Read scope on 2026-09-12: publisher HTML abstract, introduction, hierarchical
model, existing conditional-dependence models and opening quadratic-model
section. Equations omitted by HTML extraction, remaining methods, empirical
results and supplements remain unaudited. This is not replication.

The authors distinguish raw-time median splits from residual log-time effects:
the former can mix higher-level ability/speed association with within-item
dependence. They propose quadratic, multiple-category and nonparametric
approaches, including posterior predictive evaluation of linearity. Opposing
response processes may conceal dependence in a linear summary.

CO-specific proposal, not the authors' result: before fast-mlsirm supplies a
joint calibration contract, compare residual-dependence diagnostics with an
accuracy-only baseline using held-out model-family/item clusters. Preserve
generation time, queue/network time, reasoning-token count and decision-only
time as different observables. A completed response's time or correctness
cannot select that same request's initial route. Fit preprocessing only on
training data; evaluate frozen policies on subsequent observations. Reject an
uncalibrated monotonic length bonus. Neither human-test results nor this
proposal establishes LLM transfer or the existing accuracy/decision-p95 KPI.

## Executable marginal-uncertainty check

Root read §5.2, including equation (7), on 2026-09-12. That equation reports
the ability diagonal of joint posterior precision as inverse variance. For
finite joint Gaussian uncertainty with unknown speed, marginal variance instead
uses the corresponding diagonal of the inverse matrix. Conditional precision
and marginal precision coincide only when the coupling vanishes or in an
appropriate limiting argument. The asymptotic theorem's assumptions and error
order still require a full audit; this check does not refute that theorem.

Our algebraic unit check below uses fixed known likelihood information, not
simulated customer outcomes or an implementation of LaRT. It checks zero
correlation, both correlation signs, uninformative speed, and finite informative
speed. At ability information 2, speed information 3 and correlation 0.8,
marginal variance is `13/51`, whereas conditional variance is `9/43`.
Neither is a measured CO improvement. Owner implementations must label the
target uncertainty before adopting a formula.

```rust
fn marginal_variance(ability_information: f64, speed_information: f64,
                     trait_correlation: f64) -> f64 {
    let prior_precision = 1.0 / (1.0 - trait_correlation.powi(2));
    let ability_precision = ability_information + prior_precision;
    let speed_precision = speed_information + prior_precision;
    let cross_precision = -trait_correlation * prior_precision;
    let joint_determinant = ability_precision * speed_precision - cross_precision.powi(2);
    assert!(joint_determinant > 0.0);
    speed_precision / joint_determinant
}
for trait_correlation in [-0.8, 0.0, 0.8] {
    assert!((marginal_variance(2.0, 0.0, trait_correlation) - 1.0 / 3.0).abs() < 1e-12);
}
assert!((marginal_variance(2.0, 3.0, 0.0) - 1.0 / 3.0).abs() < 1e-12);
for trait_correlation in [-0.8, 0.8] {
    let observed_variance = marginal_variance(2.0, 3.0, trait_correlation);
    assert!((observed_variance - 13.0 / 51.0).abs() < 1e-12);
    assert!(observed_variance > 9.0 / 43.0);
    assert!(observed_variance < 1.0 / 3.0);
}
```

Run `rustdoc --test docs/doctoring/lart_measurement_review.md`. This manual
documentation test is not a hosted owner-estimator conformance test.

Verification receipt: at `de01e9e1`, the command above passed one Rust
documentation test in 2.89s (terminal process 2866). Root directly inspected
the title/citation area and complete Rust code block in two browser screenshots
at `http://127.0.0.1:18768/lart`, English, 1265 × 712. The inspected text and
code were legible without horizontal clipping or overlap. Middle prose,
other viewport sizes, link destinations and locales were not visually audited.
Screenshots remain in the task output, not published image assets. The shared
local preview has an exporter-oriented browser title/navigation; it is not
the product UI or evidence of published documentation.

## Additional intake — model/prompt split and theorem boundary

At official repository commit `8cb9639eb162ff3732df82d4e190e7f902bde19d`,
[data documentation](https://github.com/Toby-X/Latency-Response-Theory-Model/blob/8cb9639eb162ff3732df82d4e190e7f902bde19d/data/README.md)
describes rows as model/prompt combinations, not independent base models.
[Predictive evaluation](https://github.com/Toby-X/Latency-Response-Theory-Model/blob/8cb9639eb162ff3732df82d4e190e7f902bde19d/applications/predictive_power.py)
selects 100 of 128 rows randomly before fitting. Consequently, that split
does not itself establish unseen-base-model or unseen-family generalization.
This is an inference from the code, not a measured leakage magnitude or a
claim that the authors targeted family holdout. CO's proposed experiment must
group verified base-model/prompt siblings and keep family holdout distinct.
The matrices omit raw generations; their availability alone does not establish
complete failed-request denominators, data reuse permission, or CO latency.

Root read Appendix D.1; independent review also checked PDF pages 32–34.
Assumption 2 requires both component bounds to be negative whenever the joint
trait differs from truth. At `theta = theta_true` and `tau != tau_true`, the
accuracy log-ratio is identically zero, contradicting its strictly negative
bound. The symmetric speed-axis case also fails. Separate suprema over the
two-dimensional ball complement preserve this problem. This is a printed
quantifier inconsistency, not evidence that the intended normality conclusion
or empirical results are false. A possible repair is componentwise
nonpositivity with joint uniform separation; Lemma 4 must also be revisited.
No corrected theorem has been proved here. Primary locations:
[Appendix D.1](https://arxiv.org/html/2512.07019v4#A4.SS1) and
[PDF pages 32–34](https://arxiv.org/pdf/2512.07019v4#page=32).

Owner acceptance implication: do not treat the printed assumption as a
verified precondition for production uncertainty claims. Keep the existing
finite-matrix unit check separate from an asymptotic proof and from held-out
calibration. This intake changes no estimator or routing default; dataset
licensing/provenance audit and final rendering of this addition are pending.

### Pinned matrix identity audit

On 2026-09-12 root parsed the complete public combined correctness CSV at the
upstream commit above, without running upstream code or fitting an estimator.
Raw SHA-256: `231ea6d561e63229747de56b3c8aa8456a1ae16442945758f1ac4944df89b244`.
There are 128 rows and 100 columns, but only 40 unique column labels; 30 labels
repeat. No ragged rows, duplicate full row IDs, or nonbinary cells were found.
Column position must therefore be preserved until benchmark-qualified item
identity is established; a label-keyed join could merge distinct questions.

Reproducing only the published `RandomState(42).choice(128, 100, replace=False)`
split with NumPy 2.5.2, and stripping only explicit `_one_shot`/`_zero_shot`
suffixes for this diagnostic, gives 65 base identifiers. Of 28 held-out rows,
21 have a base identifier in training (21 shared identifiers). This verifies
overlap under that naming rule, not family ancestry or its predictive impact.
It is a read-only dataset audit, not an autoresearch treatment or KPI gain.
No response content was sent to a model; no dataset was committed.

The existing finite-uncertainty Rust documentation test passed at `a73737e4`
(session `30596`, 1 test, 1.30s). It does not test this CSV audit or prove a
corrected asymptotic theorem.

Visual follow-up: source `85fabb16` was rendered at
`http://127.0.0.1:18774/lart`, English, 1265 × 712. Root directly opened two
overlapping browser captures covering the complete additional intake and
pinned-matrix audit through its final paragraph. Text, identifiers and links
were readable without observed clipping or overlap. This supersedes the
earlier pending-render statement for these additions only. Captures remain
in the task output; other viewports/locales, link destinations and product UI
were not audited. Dataset rights and all statistical/deployment limits remain.

### Existing installed owner gate

The installed `fast-mlsirm` 0.9.1 distribution already exposes
`validate_group_partition`. Its installed `model_validation.py` SHA-256 is
`7441501eb8c9ee2fb79a8c5e8fddff4a9be9385331e5f0909c4e023eb63bd7e9`.
Root verified the site-packages origin with Python isolated mode from `/tmp`.
Passing the pinned matrix's suffix-derived group IDs and published seeded
training/evaluation fold IDs to this existing function raised the expected
cross-fold-group `ValueError` (terminal command `221880`, exit 0 because the
diagnostic explicitly required rejection). Input bytes were SHA-256 checked
before parsing. No owner source imports, external estimator execution, runtime
changes or new validation abstraction were needed.

Reuse this released identity gate for the proposed experiment. It validates
declared group boundaries, not the scientific correctness of those declarations,
family ancestry, label validity, calibration, or data rights. A manually verified
identity map remains a prerequisite; accepting a repaired partition will not
constitute successful model estimation or KPI improvement.

Verification receipt: at `1ffd5d44`, root directly opened a browser screenshot
of this complete owner-gate section at `http://127.0.0.1:18774/lart`, English,
1265 × 712. The text and complete digest wrapped legibly without observed
clipping or overlap. The capture remains in the task output; other viewports,
locales and product UI remain uninspected. The existing Rust documentation
test also passed (1 test, 1.61s; terminal command `c2e46a`); that algebra check
is separate from the installed partition-rejection evidence above.

### Preprocessing evidence successor

The four preprocessing follow-ups formerly ending at `b4887c28` are preserved
in [Draft PR #1139](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1139),
exact head `0024522146803627b8741470ebefaf79ffa4a310`. Before this normal revert,
the research head was verified as its ancestor and the successor diff contained
only additions to this note and AGENTS/CLAUDE; runtime, tests, Rust and Gap
contents were identical. This removes duplicate ownership, not the research
finding or its unresolved acceptance gates. Read the successor for all retained
cell comparisons, encoding provenance, chosen owner repair and bounded tests.
[Upstream PR #2](https://github.com/Toby-X/Latency-Response-Theory-Model/pull/2)
remains Draft at `e5c82a91918a26fab469efd9f04d5152088b5c84`; its hosted run
requires maintainer approval. Full estimator execution, data rights, held-out
accuracy and CO decision latency remain unverified. No deployment is claimed.
