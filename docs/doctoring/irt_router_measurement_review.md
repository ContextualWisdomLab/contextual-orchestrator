# IRT-Router measurement review

Status: Proposed interpretation; no routing-default change.
Reviewed 2026-09-08 against CO `c648797dfbec58dbdce60f35ed6dc5b356953387`.

## Source and visual inspection

Song, W., Huang, Z., Cheng, C., Gao, W., Xu, B., Zhao, G., Wang, F., &
Wu, R. (2025). IRT-Router: Effective and interpretable multi-LLM routing via
item response theory. In *Proceedings of the 63rd Annual Meeting of the
Association for Computational Linguistics (Volume 1: Long Papers)*
(pp. 15629–15644). Association for Computational Linguistics.
https://doi.org/10.18653/v1/2025.acl-long.761

The publisher PDF page 15633 (PDF page 5) was rendered and visually inspected,
including equations (4)–(9). Section 4.2.1 explicitly uses multidimensional
abilities, so a unidimensionality criticism would misdescribe this model.
Equation (5) predicts performance from a discrimination–ability inner product
and difficulty. Section 4.2.2 derives relevance labels using clustered query
embeddings and LLM annotation; these labels should not be treated as independently
validated constructs merely because the prediction loss is small.

## Mathematical inference, not a reported experimental result

For the MIRT prediction, any invertible matrix A preserves the logit under
`theta_new = A theta` and `a_new = A^(-T) a`, with difficulty unchanged.
Thus prediction fit alone cannot identify the meaning, orientation, or scale
of each ability coordinate. This is not a proof that IRT-Router fails at
routing, nor a claim that the entire paper contains no identification work.
It is a concrete reason not to equate predictive accuracy with validated
psychometric interpretation.

### Executable coordinate counterexample

Run `rustdoc --test docs/doctoring/irt_router_measurement_review.md` from the
repository root. This synthetic unit example exercises an invertible diagonal
rescaling, not a parameter estimator, empirical model fit, or general proof.
It uses only the Rust standard library and leaves production code unchanged.

```rust
let ability_vector = [1.0_f64, 2.0];
let discrimination_vector = [0.5_f64, 1.5];
let scale_vector = [2.0_f64, 0.5];
let transformed_ability = std::array::from_fn::<_, 2, _>(
    |axis_index| ability_vector[axis_index] * scale_vector[axis_index]);
let transformed_discrimination = std::array::from_fn::<_, 2, _>(
    |axis_index| discrimination_vector[axis_index] / scale_vector[axis_index]);
let original_logit: f64 = ability_vector.iter()
    .zip(discrimination_vector).map(|(ability_value, item_value)|
        ability_value * item_value).sum();
let transformed_logit: f64 = transformed_ability.iter()
    .zip(transformed_discrimination).map(|(ability_value, item_value)|
        ability_value * item_value).sum();
let ability_coordinate_rmse = (ability_vector.iter().zip(transformed_ability)
    .map(|(original_value, transformed_value)|
        (original_value - transformed_value).powi(2))
    .sum::<f64>() / 2.0).sqrt();
assert_eq!(original_logit, 3.5);
assert_eq!(transformed_logit, original_logit);
assert_eq!(ability_coordinate_rmse, 1.0);
```

Difficulty is unchanged, so equal inner products imply equal logits and
probabilities. These binary-exact fixture values intentionally permit exact
assertions; this is not a floating-point tolerance policy for fitted parameters.
The nonzero ability-coordinate RMSE is intentionally a single-family
counterexample. It shows why an alignment contract is required before
interpreting ability recovery, even when predictions agree exactly. This
example does not validate discrimination recovery. A production report must
apply the same alignment and RMSE calculation independently to
`discrimination_vector`, `difficulty_vector`, and every other declared family,
with a family-specific assertion or fixture for each one.

## CO acceptance implications

- Keep parameter-recovery RMSE separate from observed-task prediction error.
  Every recovered parameter family requires its own declared identification
  map into a common reference coordinate. Compute family-wise RMSE only after
  applying that map to both truth and estimates; if a family's map is not
  identified, its recovery result is undefined and must not enter an aggregate.
  Arbitrary coordinate RMSE can penalize equivalent predictions.
- Before interpreting ability labels, require evidence for the proposed
  construct anchors, dimensional structure, residual dependence, and stability
  across language, task, model family, and time. These are review requirements,
  not findings already demonstrated against the authors' data.
- Evaluate observed task outcomes on a declared sampling design, retaining
  failed deliveries in the denominator and reporting uncertainty. Measure
  decision latency independently under the interval in
  [the analytics specification](../analytics_spec.md).
- Mathematical fitting and diagnostics remain the responsibility of released
  fast-mlsirm contracts. CO must not implement a competing estimator or turn
  this literature note into permission to alter production defaults.

Related: [ADR 0005](../planning/adrs/0005-irt-response-matrix-contract.md).
Its matrix-shape validation is necessary boundary checking, not identification
or construct-validity evidence.

## Response-time research extension (2026-09-09)

Status: proposed research, not a fitted model or production policy. Repository
inspection at `29f417f256f8e50651b49506c042c5ec882ff472` found no reference
matching `van der Linden`, `speed.accuracy`, or `response.time model` in tracked
text. This bounded search does not establish an exhaustive literature inventory.

van der Linden, W. J. (2007). A hierarchical framework for modeling speed and
accuracy on test items. *Psychometrika, 72*(3), 287–308.
https://doi.org/10.1007/s11336-006-1478-z

The publisher confirms the final article's bibliographic identity. The separately
available [RR 05-02 report](https://ris.utwente.nl/ws/files/5129699/Linden05hierarchical.pdf)
is an earlier version, not verified identical to the journal article. Its printed
page 6 (PDF page 10) was rendered and visually inspected: equations (8)–(14)
separate response ability from response speed, specify a lognormal time model,
and combine person parameters at a second level. The response/time likelihood
factorization assumes conditional independence given the latent parameters.
The inspected report is linked, not redistributed; redistribution permission
has not been established.

### CO hypothesis and acceptance boundary

The following is our proposed application, not a result reported by the paper.
A joint outcome/time model might improve calibration for repeated observed
tasks, but provider generation duration cannot substitute for CO's accepted
request-to-persisted-decision interval. Keep both measurements separate. Provider
load, output length, reasoning settings, retries, and transport failures can
change completion time without changing the intended ability construct.
Do not infer that a faster provider is more capable or add an arbitrary
speed-weighted ability score.

For an observed-task experiment, compare outcome-only and joint models on the
same predeclared held-out tasks and model revisions, with model/task/time
grouping retained. Report calibration and delivered-correct fraction over all
accepted requests, plus failure and censoring counts. Check residual dependence
and held-out time fit before using the joint model. Fitting and diagnostics
belong in released fast-mlsirm contracts; CO consumes their versioned outputs.

The decision-latency experiment remains separate: profile selection and durable
write costs under the analytics interval before choosing a runtime optimization.
A joint estimator on the request path could increase that latency. No estimator
is added here: neither observed training/held-out data nor released joint-model
support has been verified. The next experiment must establish that baseline
before claiming improvement, rather than using oracle-score fixtures as buyer
evidence.

### Conditional-dependence follow-up

Bolsinova, M., & Tijmstra, J. (2019). Modeling differences between response
times of correct and incorrect responses. *Psychometrika, 84*(4), 1018–1046.
https://doi.org/10.1007/s11336-019-09682-5

Read scope on 2026-09-09: publisher abstract and bibliographic information,
not equations, supplementary material, or a reproduced experiment. The
publisher page displays an online date in 2025, but its volume/issue identifies
the article as December 2019; the citation uses the issue year.

The abstract describes extensions that permit speed-model item parameters to
differ for correct and incorrect responses, including separate latent speeds.
It reports simulation and assessment-data applications, not LLM-routing results.
This gives a concrete alternative to assuming conditional independence in the
joint-model proposal above.

Engineering inference: compare the independence baseline with this conditional
model on the same held-out design. Correctness is unavailable at routing time:
using the observed outcome to choose a speed component would leak the target.
Any deployable prediction must marginalize unknown outcomes; oracle-conditioned
fit is not a routing KPI. The fitting owner remains fast-mlsirm. No new request-path
estimator or production default is introduced, and full-method review is pending.

### Response-process identification follow-up

Bolsinova, M., Tijmstra, J., Molenaar, D., & De Boeck, P. (2017).
Conditional dependence between response time and accuracy: An overview of its
possible sources and directions for distinguishing between them. *Frontiers in
Psychology, 8*, Article 202. https://doi.org/10.3389/fpsyg.2017.00202

Read scope: publisher HTML Sections 1–4 on 2026-09-09, with Figure 1 opened
and directly inspected in the actual browser at 1265 × 712, English. Panels
A–E and arrows were readable; the separate caption pane required scrolling.
The initial capture preceded image loading; the second capture confirmed the
diagram. This is a perspective, not a reproduced numerical experiment. The
paper explains why residual time/accuracy association may reflect different
response processes, and why its sign alone does not identify their cause.
Section 4 recommends hypothesis-relevant covariates and model comparisons,
including residual checks. It does not provide a complete estimation algorithm.

CO engineering proposal at research head `946726408556c3145ee5c996905f5bd5e907645e`:
predeclare model revision, task family, policy revision and configured effort as
available-before-decision covariates. Record realized cache, auxiliary work,
fallback and failure states separately as diagnostics; do not use future
outcomes or realized durations to predict the same request's initial route.
Do not label a latent class “reasoning” merely because its answers took longer.
Compare an outcome-only baseline, a joint independence model and a
covariate-extended model on the same held-out groups before choosing complexity.
Estimation remains a fast-mlsirm responsibility, with a released contract and
predictive checks required before CO adoption. No new estimator is implemented.

This sharpens the existing KPI experiment rather than changing its targets:
the initial-task decision interval remains distinct from generation duration;
success and failure denominators must retain every request in the declared
cohort. Completeness still requires reconciliation with external ingress.
Candidate #1110 `3b6dd47ebb0f88802bacdd302051d2f03e7d5003` now retains
admitted semantic rejection as selection failure. Its local focused suite passed
83 tests; full-suite and production observation evidence remain separate gates.
