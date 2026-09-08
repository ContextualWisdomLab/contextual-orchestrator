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
The nonzero ability-coordinate RMSE is a single-family counterexample: it
shows why an alignment contract is required before interpreting ability
recovery, even when predictions agree exactly. It does not validate recovery
for discrimination, difficulty, or any other parameter family.

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
