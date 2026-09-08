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

## CO acceptance implications

- Keep parameter-recovery RMSE separate from observed-task prediction error.
  Recovery requires known parameters and a declared identification/alignment
  contract; arbitrary coordinate RMSE can penalize equivalent predictions.
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
