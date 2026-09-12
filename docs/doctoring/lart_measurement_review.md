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
