---
id: "0139"
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

# ADR 0139: Judge the conduct response candidate against the verifier report

## Problem

Both fixed-template and generated `conduct` workflows sent the verifier's
review report to `ContextualOrchestratorJudge` as its `answer`. The result then
controlled whether the runtime returned a worker or synthesizer output. A
quality judgment about the review report does not measure either response
candidate and therefore cannot support that selection.

## Scope

This ADR changes only *which text is judged* in `conduct`. It does not change
how answers are scored:

- `accept_threshold` stays `0.7` on every path.
- The criteria stay `evidence_quality` and `risk_signal` (weight `1.0` each,
  same order and descriptions) on every path, including `conduct`.
  `psychometric_routing.py` stores IRT rows by column position without
  criterion ids, so renaming or reordering criteria would silently change the
  meaning of rows already recorded.
- Direct routes (`route_once`, streaming, and batch, all through
  `_realtime_route_judge`) are unchanged: the one response is both the answer
  under review and the stored `verifier_output`, and no reference is passed.

A scoring redesign (a different threshold such as a conjunctive `1.0` rule,
or criteria that describe a final answer rather than "the verifier output") is
out of scope. It needs its own PR and ADR with evaluation evidence and a plan
for the positional psychometric rows. An intermediate revision of this PR
(`350da480`) included such a redesign; it was removed.

## Constraints

- fast-mlsirm remains the only semantic judge; contextual-orchestrator must not
  implement a lexical or arithmetic substitute.
- The verifier report remains available as evidence and must not be relabelled
  as the final answer.
- Missing, malformed, or unavailable judge output fails closed (ADR 0001).

## Alternatives

1. **Keep judging the verifier report.** Rejected because the measured object
   differs from the returned object.
2. **Disable judgment when `verifier_required=False`.** Rejected because it
   would remove evidence rather than repair the quality boundary.
3. **Judge the response candidate and pass the verifier report as
   `reference_answer`, with scoring unchanged.** Selected.

## Decision

`_model_judge_verification` accepts an optional `answer`. Conduct callers (the
template and the generated plan) pass their final workflow-step output as
`answer`, and the verifier report goes to fast-mlsirm as `reference_answer`.
fast-mlsirm treats the reference as a comparison standard, not as evidence:
its prompt says requirements written only in the reference must not be
credited to the answer. Direct-route callers omit `answer` and the call is
exactly as before (no `reference_answer`).

Known limitation: the unchanged criterion descriptions still ask about "the
verifier output". With `answer` now the final response, the judge scores that
response against those descriptions. Rewording them belongs to the scoring
redesign above.

## Evidence

`tests/test_orchestrator_dispatch_boundaries.py`:

- `test_conduct_judges_the_final_answer_against_the_verifier_reference`
  (template and generated) fails at the approved predecessor `235bf8fb`
  (captured `answer` is the verifier report) and passes now. It also pins
  threshold `0.7` and `evidence_quality`/`risk_signal` for conduct.
- `test_route_once_judge_keeps_the_direct_route_contract` and
  `test_realtime_route_judge_keeps_the_direct_route_contract` pin the direct
  route: the response is the answer, no `reference_answer`, threshold `0.7`,
  and main's criteria. At `350da480` both fail (threshold `1.0`, renamed
  criteria).

## Effects and risks

- A conduct verdict now describes the response candidate that may be returned.
- The verifier report remains auditable as reference evidence.
- Direct-route verdicts, quality-ledger observations, psychometric rows, and
  cascade behavior are unchanged.
- This does not establish held-out judge accuracy, inter-rater reliability, or
  a calibrated decision policy; `0.7` stays an uncalibrated legacy value.
- `verifier_required=False` still permits a rejected synthesis to be returned;
  that explicit opt-out remains a separate policy question and must not be
  described as fail-closed publication.

## Operational scenes

- **Normal:** the synthesizer addresses the verifier's findings; the judge
  scores the synthesis with the report as reference and the weighted score
  reaches `0.7`.
- **Failure:** the synthesis scores below `0.7`; a required-verifier workflow
  falls back to the worker output according to its existing policy.
- **Unavailable judge:** fast-mlsirm or the provider fails; the verdict remains
  rejected and records available call accounting.
- **Optional verifier policy:** the rejected verdict remains visible even when
  the caller explicitly configured it not to gate the returned synthesis.

## Follow-up

A scoring redesign (threshold and criteria) needs its own PR and ADR with
evaluation evidence and a migration or versioning plan for the positional
psychometric rows. fast-mlsirm should own and release a versioned calibrated
decision-policy contract; contextual-orchestrator can consume that release in
a later PR.
