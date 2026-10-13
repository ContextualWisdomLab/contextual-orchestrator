---
id: "0050"
title: "Declare held-out candidate-group DIF protocol"
status: proposed
proposed_date: "2026-09-08"
deciders:
  - "repository maintainer"
affected_components:
  - "scripts/benchmark_psychometric_heldout.py"
related:
  - path: "docs/planning/adrs/0049-declared-assignment-trials.md"
    relation: extends
success_criteria:
  - metric: "no hidden DIF sample default"
    target: "omitted, non-positive, or odd sample_size fails closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_candidate_group_dif_requires_declared_sample_size"
  - metric: "declared count is the DIF population"
    target: "report sample_size equals the declared even count"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_candidate_group_dif_uses_declared_sample_size"
  - metric: "no hidden DIF algorithm controls"
    target: "missing FDR, solver, purification, or anchor declarations fail closed"
    source: "tests/test_psychometric_benchmark_boundaries.py::test_candidate_group_dif_requires_declared_sample_size"
---

# ADR 0050: Declare held-out candidate-group DIF protocol

- Status: Proposed
- Date: 2026-09-08
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

Buyer-facing candidate-group DIF evidence must be reconstructible. A hidden
`DIF_SAMPLE_SIZE = 4_000` chose Monte Carlo precision for two equal cohorts
without an operator declaration. fast-mlsirm 0.11.4 also removed the
unsourced `fdr_q`, IRLS iteration, purification-round, and minimum-anchor
defaults from `detect_dif_logistic_purified`; continuing to call a deprecated
alias would have hidden those controls again.

## Decision

In the context of the held-out purified logistic DIF screen, we chose required
declarations for the even `sample_size`, `exclude_studied_item`, `fdr_q`,
`max_iter`, `max_rounds`, and `min_anchor_items`, and against restoring
library defaults. Omitted,
non-finite, or invalid declarations fail closed before fast-mlsirm runs.

The script entry point freezes and reports the pre-0.11.4 comparison protocol:
4,000 rows, studied-item inclusion in the matching score, a declared
Benjamini-Hochberg target of 0.05, 50 IRLS iterations, three purification
rounds, and four minimum anchor items. These are
reproducibility inputs for this synthetic fixture, not reusable library or
production routing defaults. The benchmark records all six values, verifies
all eight item fits and purification convergence before known injected-DIF
recovery, and leaves the
buyer-validity production gate unexecuted. The method and its limits follow
Candell and Drasgow (1988), French and Maller (2007), and Zumbo (1999), as
documented by fast-mlsirm's released API. Benjamini-Hochberg adjustment is a
screen here; data-dependent purification does not inherit an FDR-control
claim. Odd sample counts fail closed so the cohorts stay equal.

## Alternatives considered

- Keep 4,000 or the algorithm controls as callable defaults. Rejected: this
  hides decision and precision inputs from the report consumer.
- Allow odd counts and drop one row. Rejected: silent truncation would hide
  the declared population.
- Keep calling the deprecated alias. Rejected: warnings-as-errors correctly
  expose that the alias conceals the new required owner contract.

## Consequences

Positive: the full DIF protocol and `8 attempted / 0 failed` item-fit
denominator are reconstructible from the report and helper signature, and the
released fast-mlsirm API is used without deprecation.

Negative: callers of `_validate_candidate_group_dif` and `run_benchmark` must
declare every DIF control explicitly.

## Remaining work

Score-reliability sample size moves to ADR 0051. Other repository-authored
harness sample sizes stay open. This ADR is Proposed until independent
review and protected delivery.

## References

Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate:
A practical and powerful approach to multiple testing. *Journal of the Royal
Statistical Society: Series B (Methodological), 57*(1), 289–300.

Candell, G. L., & Drasgow, F. (1988). An iterative procedure for linking
metrics and assessing item bias in item response theory. *Applied
Psychological Measurement, 12*(3), 253–260.
https://doi.org/10.1177/014662168801200304

French, B. F., & Maller, S. J. (2007). Iterative purification and effect size
use with logistic regression for differential item functioning detection.
*Educational and Psychological Measurement, 67*(3), 373–393.
https://doi.org/10.1177/0013164406294781

Zumbo, B. D. (1999). *A handbook on the theory and methods of differential
item functioning (DIF): Logistic regression modeling as a unitary framework
for binary and Likert-type (ordinal) item scores*. Directorate of Human
Resources Research and Evaluation, Department of National Defense.
