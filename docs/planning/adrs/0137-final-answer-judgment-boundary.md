---
id: "0137"
title: "Judge the conduct response candidate against the verifier report"
status: proposed
proposed_date: "2026-09-27"
deciders:
  - "repository maintainer"
consulted:
  - "contextual-orchestrator runtime"
  - "released fast-mlsirm judge contract (`reference_answer` argument)"
informed:
  - "conduct API consumers"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "tests/test_orchestrator_dispatch_boundaries.py"
  - "tests/test_model_judge.py"
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: refines
---

# ADR 0137: Judge the conduct response candidate against the verifier report

## Problem

Both fixed-template and generated `conduct` workflows sent the verifier's
review report to `ContextualOrchestratorJudge` as its `answer`. The result then
controlled whether the runtime returned a worker or synthesizer output. A
quality judgment about the review report does not measure either response
candidate and therefore cannot support that selection.

## Constraints

- fast-mlsirm remains the only semantic judge; contextual-orchestrator must not
  implement a lexical or arithmetic substitute.
- The verifier report remains available as evidence and must not be relabelled
  as the final answer.
- Missing, malformed, or unavailable judge output fails closed (ADR 0001).
- Direct routes (`route_once`, streaming, and batch, all through
  `_realtime_route_judge`) must not change: there the one response is both the
  answer under review and the stored `verifier_output`.
- No acceptance-threshold change without evaluation evidence. The existing
  `accept_threshold=0.7` has no calibration artifact either, but replacing it
  is a separate, evaluated decision, not part of this fix.

## Alternatives

1. **Keep judging the verifier report.** Rejected because the measured object
   differs from the returned object.
2. **Disable judgment when `verifier_required=False`.** Rejected because it
   would remove evidence rather than repair the quality boundary.
3. **Also raise the threshold to `1.0` (every criterion at its maximum).**
   Rejected. It was not requested and has no evaluation behind it; with
   continuous criterion scores it would reject almost every conduct final
   answer and force the worker fallback. An earlier revision of this PR
   (`350da480`) applied it to every judged path, including direct routes.
4. **Judge the response candidate, pass the verifier report as
   `reference_answer`, keep the `0.7` threshold, and use criteria that describe
   a final answer.** Selected.

## Decision

`_model_judge_verification` accepts an optional `answer`.

- **Conduct final answer** (`answer` supplied by both the template and the
  generated plan): fast-mlsirm judges the final workflow-step output as
  `answer` and receives the verifier report as `reference_answer`. fast-mlsirm
  treats the reference as a comparison standard, not as evidence: its prompt
  says requirements written only in the reference must not be credited to the
  answer. The criteria are `task_alignment` ("Does the response directly and
  completely address the requested task?") and `evidential_support` ("Are
  material claims supported, with every substantive verifier finding resolved
  or explicitly reported?"), each with `weight=1.0`.
- **Direct routes** (`answer` omitted): unchanged. fast-mlsirm judges the
  response itself, with no `reference_answer`, using the `evidence_quality` and
  `risk_signal` criteria (weight `1.0` each) exactly as before.
- **Both paths** construct the judge with `accept_threshold=0.7`.

The conduct criteria differ from the direct-route ones only because the
direct-route criteria ask about "the verifier output"; applied to a
synthesizer answer they would describe the wrong object. Keeping the threshold
and weights identical isolates the change to *what* is judged.

## Evidence

At `350da480`, and at the approved predecessor `235bf8fb`, the regression
tests in `tests/test_orchestrator_dispatch_boundaries.py` fail:

- `test_conduct_judges_the_final_answer_against_the_verifier_reference`
  (template and generated): at `235bf8fb` the captured `answer` is the
  verifier output; at `350da480` the threshold is `1.0`.
- `test_route_once_judge_keeps_the_direct_route_contract` and
  `test_realtime_route_judge_keeps_the_direct_route_contract`: at `350da480`
  direct routes use `1.0` and the conduct criteria.

After this revision all of them pass, together with
`tests/test_model_judge.py::test_fast_mlsirm_judge_contract_does_not_pass_threshold_to_judge_call`
(`0.7` again).

## Effects and risks

- A conduct verdict now describes the response candidate that may be returned.
- The verifier report remains auditable as reference evidence.
- Direct-route verdicts, quality-ledger observations, and cascade behavior are
  unchanged.
- This does not establish held-out judge accuracy, inter-rater reliability, or
  a calibrated decision policy; `0.7` stays an uncalibrated legacy value.
- `verifier_required=False` still permits a rejected synthesis to be returned;
  that explicit opt-out remains a separate policy question and must not be
  described as fail-closed publication.

## Operational scenes

- **Normal:** the synthesizer resolves the verifier's findings; the judge scores
  the synthesis against the report and the weighted score reaches `0.7`.
- **Failure:** the synthesizer ignores a concrete verifier finding; evidential
  support scores low, so a required-verifier workflow falls back to the worker
  output according to its existing policy.
- **Unavailable judge:** fast-mlsirm or the provider fails; the verdict remains
  rejected and records available call accounting.
- **Optional verifier policy:** the rejected verdict remains visible even when
  the caller explicitly configured it not to gate the returned synthesis.

## Follow-up

Any threshold change (including a conjunctive `1.0` rule) needs its own
proposal with evaluation evidence. fast-mlsirm should own and release a
versioned calibrated decision-policy contract with held-out design, estimator
identity, uncertainty, criterion provenance, and immutable artifact digest.
contextual-orchestrator can consume that release in a later PR; no source copy
or mutable branch dependency is authorized.
