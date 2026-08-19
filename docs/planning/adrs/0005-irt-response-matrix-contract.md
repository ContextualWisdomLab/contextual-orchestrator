---
id: "0005"
title: "Require multi-item response matrices at the IRT integration boundary"
status: accepted
proposed_date: "2026-08-11"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "fast-mlsirm IRT response validators"
  - "fast-mlsirm LLM judge adapter"
informed:
  - "contributors"
affected_components:
  - "fast-mlsirm/python/fast_mlsirm/irt_contract.py"
  - "fast-mlsirm/python/fast_mlsirm/llm_judge.py"
  - "fast-mlsirm/tests/test_irt_contract.py"
  - "fast-mlsirm/tests/test_llm_judge.py"
effort: S
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: informational
  - path: "docs/planning/adrs/0002-explicit-local-mlx-evaluation.md"
    relation: informational
asr_triggers:
  - kind: maintainability
    evidence: "A scalar judge score has no item dimension and cannot identify multiple IRT item responses."
    note: "The public integration validator rejects one-item response matrices."
  - kind: maintainability
    evidence: "Low-level fast-mlsirm numerical primitives intentionally accept some one-item diagnostic inputs."
    note: "The cross-component contract is isolated instead of silently changing every numerical primitive."
success_criteria:
  - metric: "IRT item columns"
    target: "every cross-component dichotomous or polytomous matrix has at least two item columns"
    measurement_window: "every adapter-to-IRT conversion"
    source: "validate_irt_response_matrix and regression tests"
  - metric: "response-domain validation"
    target: "invalid shape, non-binary values, invalid category indices, infinities, and implicit polytomous category counts are rejected"
    measurement_window: "every validation call"
    source: "fast-mlsirm/tests/test_irt_contract.py"
---

# Require multi-item response matrices at the IRT integration boundary

## Context

fast-mlsirm exposes dichotomous and polytomous numerical primitives, but an
LLM-as-a-Judge normally produces one scalar decision or one scalar per rubric.
That scalar is not an IRT response matrix. The user clarified that an IRT
result must contain multiple dichotomous items or multiple polytomous items.

> Existing fast-mlsirm response APIs describe inputs as persons by items, while several low-level validators allow one item for numerical tests.
>
> LLMJudgeResult previously exposed criterion scores but had no explicit conversion boundary for IRT item rows.
>
> A missing item dimension, an inferred category count, or a continuous score silently coerced into one item can produce an apparently valid but scientifically invalid IRT run.

## Decision Drivers

* Make the user’s multi-item IRT requirement executable at the integration boundary.
* Keep missing responses, binary domains, and ordered category domains explicit.
* Avoid breaking low-level one-item diagnostics that are useful for numerical and security tests.
* Prevent a single LLM verdict from being represented as a fake item bank.

## Considered Options

* Let each IRT model decide whether a single item is acceptable.
* Globally change every fast-mlsirm numerical primitive to require two items.
* Add one public cross-component validator and require LLM judge projections to expose multiple criterion items.

## Decision Outcome

Chosen option: "Validate multi-item response matrices at the cross-component boundary".

| Driver | Model-local checks | Global breaking check | Shared integration validator |
| --- | --- | --- | --- |
| User contract | inconsistent | enforced but broad | enforced where results cross systems |
| Compatibility | high | low | high for existing primitives |
| Error observability | scattered | mixed | one actionable error boundary |
| LLM scalar misuse | possible | partly prevented | rejected explicitly |

The public validate_irt_response_matrix function accepts a 2-D persons by
items matrix with at least two item columns. Dichotomous observed values are
0/1; polytomous values are integer indices from 0 through K-1 and require an
explicit K. NaN is the only missing-value marker. LLMJudgeResult.to_irt_row
requires at least two criteria and produces a deterministic row for an
explicitly requested dichotomous or polytomous projection.

The projection is a shape and domain bridge, not a claim of unbiased
measurement. Category-count and prompt-perturbation calibration remain
mandatory under ADR 0006.

### Consequences

* Good, because one-item and scalar outputs fail before reaching an IRT model.
* Good, because category semantics and missingness are explicit and testable.
* Good, because existing numerical primitives retain their current narrow
  diagnostic behavior.
* Bad, because callers must collect multiple rubric criteria and multiple
  persons before fitting a meaningful model.
* Bad, because equal-width projection from continuous judge scores can retain
  judge bias; it is intentionally not a calibration substitute.

## Pros and Cons of the Options

### Model-local checks

* Good, because there is no new public helper.
* Bad, because a scalar emitted by an external judge can still be misrouted.
* Bad, because each model family can drift in shape and missing-value behavior.

### Global breaking check

* Good, because every numerical entry point would enforce the same minimum.
* Bad, because low-level diagnostics and existing compatibility tests use
  one-item inputs intentionally.
* Bad, because a broad breaking change does not explain whether the source
  result had multiple rubric items.

### Shared integration validator (chosen)

* Good, because it enforces the requirement exactly where external results
  become IRT data.
* Good, because it keeps the numerical core stable and makes the contract
  reusable by future adapters.
* Bad, because callers can bypass it if they deliberately call low-level
  functions; documentation and review must keep the boundary visible.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| A scalar LLM verdict is not an IRT item matrix. | Require at least two criterion items in LLMJudgeResult.to_irt_row. | Implemented |
| A one-item persons-by-items matrix can look structurally valid. | Reject fewer than two item columns in the public integration validator. | Implemented |
| Polytomous category count can be inferred from a partial sample. | Require explicit n_categories at the integration boundary. | Implemented |
| Continuous criterion scores are not inherently ordinal observations. | Keep the projection explicit and calibrate category-count effects before fitting. | Ongoing |
| IRT estimation quality also depends on persons, item information, and factor coverage. | Add sample-size, item-information, and factor-anchor gates to the benchmark before interpreting fit. | Required next |
| Public numerical fitters could still receive one-item matrices when a caller bypassed the cross-component helper. | Enforce the same multi-item validator at public IRT fitter boundaries while leaving explicitly diagnostic low-level primitives compatible. | Implemented on fast-mlsirm follow-up branch; exact-head integration pending |
| contextual-orchestrator previously discarded fast-mlsirm criterion scores after deriving accepted/rejected, so downstream IRT consumers could not see the multi-item output contract. | Preserve only validated criterion scores and the fast-mlsirm dichotomous multi-item projection in verification metadata; reject an invalid projection rather than padding, collapsing, or repairing it. | Implemented in current local head; exact-head CI/review follow-up required |
| Low-level APIs and integration APIs have different compatibility goals. | Keep this contract documented and do not silently apply it to every existing primitive. | Implemented |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| Callers bypass the validator. | medium | high | Export one public helper, test the LLM projection, and review IRT call sites for direct coercion. | maintainer |
| Equal-width bins create artificial category thresholds. | high | high | Run category-count perturbation and calibration experiments; do not report uncalibrated IRT estimates as ground truth. | evaluation owner |
| Requiring multiple criteria reduces one-criterion convenience. | medium | medium | Preserve ordinary scalar judge use; enforce the requirement only in to_irt_row. | maintainer |

## Rollback / Exit Strategy

If compatibility evidence requires one-item numerical primitives, retain the
integration validator and revert only an overly broad caller-level adoption.
Do not remove the multi-item contract or silently convert a scalar judge result
into an IRT item.

## Affected Components

* fast-mlsirm/python/fast_mlsirm/irt_contract.py
* fast-mlsirm/python/fast_mlsirm/llm_judge.py
* fast-mlsirm/tests/test_irt_contract.py
* fast-mlsirm/tests/test_llm_judge.py
* downstream IRT adapters and benchmark data preparation

## More Information

The local Zotero library now contains the IRT and response-category references
used for this decision. Relevant local item keys are MYPNHHWJ (ordered response
categories), CWY355RP (response categories), and DXADSGKY (IRT introduction).
The implementation and review gate are intentionally independent of any single
publisher or LLM provider.
