---
title: "Judge the response candidate under a conjunctive fast-mlsirm contract"
status: proposed
proposed_date: "2026-09-27"
deciders:
  - "repository maintainer"
consulted:
  - "contextual-orchestrator runtime"
  - "released fast-mlsirm 0.9.1 contract"
informed:
  - "conduct API consumers"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "tests/test_orchestrator_dispatch_boundaries.py"
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: refines
---

# Judge the response candidate under a conjunctive fast-mlsirm contract

## Problem

Both fixed-template and generated `conduct` workflows sent the verifier's
review report to `ContextualOrchestratorJudge` as its `answer`. The result then
controlled whether the runtime returned a worker or synthesizer output. A
quality judgment about the review report does not measure either response
candidate and therefore cannot support that selection.

The same boundary supplied `accept_threshold=0.7` and two equal weights without
a calibration artifact, validation dataset, estimator identity, or cited
decision model. Those numbers affected acceptance but had no executable
provenance.

## Constraints

- fast-mlsirm remains the only semantic judge; contextual-orchestrator must not
  implement a lexical or arithmetic substitute.
- The verifier report remains available as evidence and must not be relabelled
  as the final answer.
- Missing, malformed, or unavailable judge output fails closed.
- Direct-route behavior remains compatible: there the one response is both the
  answer under review and the stored `verifier_output`.
- This Proposed change is not an immutable release or protected-branch
  authority.

## Alternatives

1. **Keep judging the verifier report.** Rejected because the measured object
   differs from the returned object.
2. **Keep the `0.7` weighted average.** Rejected because no released
   calibration or research-backed decision policy establishes that cutoff or
   the relative weights.
3. **Disable judgment when `verifier_required=False`.** Rejected because it
   would remove evidence rather than repair the quality boundary.
4. **Judge the response candidate, use the verifier report as reference
   evidence, and require every mandatory criterion to attain its maximum.**
   Selected. With positive criterion weights and a maximum score of `1.0`, the
   aggregate equals `1.0` if and only if every criterion equals `1.0`; weights
   cannot change the decision. The unit boundary is therefore the identity of
   a logical conjunction, not a fitted cutoff.

## Decision

`_model_judge_verification` accepts an optional response candidate. Conduct
callers pass their final workflow-step output as that candidate and pass the
verifier report to fast-mlsirm as `reference_answer`. The two mandatory
criteria are task alignment and evidential support, including resolution or
explicit reporting of substantive verifier findings.

The judge is constructed with `accept_threshold=1.0`; criteria omit explicit
weights. Direct-route callers omit the new argument and retain the established
single-answer behavior.

## Evidence

At PR #1264 predecessor head
`235bf8fbbea7720e051245cedef9ccf7fb325f78`, the new template/generated
regression failed twice: captured `answer` was the verifier output. Source
inspection also showed literal `accept_threshold=0.7` and `weight=1.0` at the
decision boundary. After the repair, the focused boundary and judge suites
report `74 passed`. A 13-file direct-impact run reports `443 passed / 23
failed`; the unchanged predecessor reports `441 passed / the same 23 failed`
under the same interpreter, so this delta adds two passing regressions without
adding a failure. Exact-head hosted Checks remain outstanding.

## Effects and risks

- A conduct verdict now describes the response candidate that may be returned.
- The verifier report remains auditable reference evidence.
- The conjunction is intentionally conservative and may reject responses that
  a calibrated future policy would accept.
- This does not establish held-out judge accuracy, inter-rater reliability,
  measurement invariance, or a general fast-mlsirm calibrated decision policy.
- `verifier_required=False` still permits a rejected synthesis to be returned;
  that explicit opt-out remains a separate policy question and must not be
  described as fail-closed publication.

## Operational scenes

- **Normal:** the synthesizer resolves every substantive verifier finding; the
  judge evaluates that synthesis against the report and both required criteria
  attain their maximum.
- **Failure:** the synthesizer ignores a concrete verifier finding; evidential
  support is not maximal, so a required-verifier workflow falls back according
  to its existing policy.
- **Unavailable judge:** fast-mlsirm or the provider fails; the verdict remains
  rejected and records available call accounting.
- **Optional verifier policy:** the rejected verdict remains visible even when
  the caller explicitly configured it not to gate the returned synthesis.

## Follow-up

fast-mlsirm should own and release a versioned calibrated decision-policy
contract with held-out design, estimator identity, uncertainty, criterion
provenance, and immutable artifact digest. contextual-orchestrator can consume
that release in a later PR; no source copy or mutable branch dependency is
authorized.
