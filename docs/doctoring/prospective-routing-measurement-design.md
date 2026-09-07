# Prospective routing measurement design

Status: Proposed; not an implemented decision policy. Reviewed 2026-09-07.

## Research basis and its limits

Lakens, D. (2022). Sample size justification. *Collabra: Psychology, 8*(1),
Article 33267. https://doi.org/10.1525/collabra.33267

Lakens discusses sample size in relation to inferential goals, precision,
power and useful effect sizes. A conventional count does not establish
informativeness. Sequential sampling needs a compatible analysis. The paper
supplies neither a universal routing sample size nor a p95 guarantee.

The [university-hosted publication](https://pure.tue.nl/ws/portalfiles/portal/214011492/collabra_2022_8_1_33267.pdf)
was inspected. Actual Edge visual inspection of page 12/29 (printed 11)
showed Figure 5: a correlation example with N=30, alpha=.05, critical r≈±.361.
It does not prescribe routing sample sizes. No committed screenshot is claimed.

Printed page 22 states CC BY 4.0; the added university cover has redistribution
restrictions. The publisher PDF retrieval failed. We link this combined file
pending clarification of its cover, without denying the article's open license.

## Product decision that remains open

[Issue #568](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/568)
closed when [PR #785](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/785)
merged as `4100b325c967bb50ccb23a95f3f79daf1c004ef7`. That PR records profile
binding and estimated synthetic checks, not a measured buyer improvement.
The experimental requirement already has an open owner in
[issue #86](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/86):
fair comparisons, paired uncertainty, explicit live evidence and protected
operational acceptance. Continue there rather than equating the profile issue's
closure with scientific validation or creating a duplicate evidence issue.

Removing count-only promotion prevents unsupported approval; it does not
establish an accurate, faster router. Before collecting decision evidence,
record the target task population, eligibility rules, versioned model/endpoint
and inference policies, scorer identity and rubric, planned task-policy cells,
repeated-attempt identity, and allocation order. Lock these separately from
exploratory observations. Compare emitted rows with the planned matrix:
an omitted observation is not an explicit failed delivery.

| Claim | Observable quantity | Evidence still needed |
| --- | --- | --- |
| Delivered answer quality | Paired score difference, including failed deliveries under the declared scoring rule | Representative held-out tasks, calibrated scorer, meaningful improvement or noninferiority margin and dependence-aware uncertainty |
| Routing decision speed | Per-request decision duration with the same candidate set and cache/state conditions | Prospective timing protocol, all eligible requests, uncertainty and correctness parity |
| User waiting time | End-to-end terminal-outcome latency, with failures distinguished from completed answers | Failure-inclusive outcomes and separately justified tail-latency inference; early failure is not a quality improvement |
| Psychometric recovery/transfer | Parameter error against known truth where available; stability across linked calibrations | Synthetic recovery only as a unit check, plus construct, linking, local-dependence, rater and population-transfer evidence for real use |

These are CO engineering requirements, not a new estimator or formulas claimed
to come from Lakens. Choose useful effect/precision targets from the task's
error costs and service requirement before inspecting candidate improvements.
Independent pilot information may inform variance and dependence assumptions;
its provenance and uncertainty must be recorded. Do not tune the target to an
observed result or infer a population guarantee from a successful fixture.

The analysis must use the released canonical statistical owner's contract.
No copied branch implementation, custom Python kernel, or substituted constant
is authorized by this document. Fix the sampling limit and analysis/stopping
rule prospectively. Repeatedly inspecting fixed-sample intervals does not create
a valid sequential policy. Mean-score evidence cannot substitute for tail
latency or psychometric construct validation.

## Exact-source evidence and alternatives

### Canonical statistical owner readiness (2026-09-07)

The existing owner work is [RankWeave PR #41](https://github.com/ContextualWisdomLab/RankWeave/pull/41)
and [issue #45](https://github.com/ContextualWisdomLab/RankWeave/issues/45).
The [CO consumer-contract handoff](https://github.com/ContextualWisdomLab/RankWeave/pull/41#issuecomment-5564417339)
connects this design and CO #86 without introducing another kernel or owner PR.

Released `v0.18.0` resolves to
`61c49c50d3b4a24fc9bd7c6d3a7f2f4ba19d7be6`. Its inspected TREC/retrieval
comparison contract does not prove a released generic LLM-score or terminal-
latency uncertainty API. Do not encode arbitrary outcomes as artificial
retrieval rankings to fit that interface. PR #41 at
`529b915c0f2c282d915172f9f75b17caf7016008` is Draft; its proposed `v0.19.0`
native paired-p95 contract is not a published dependency.

Before adoption, require immutable release/artifact provenance and installed-
artifact conformance fixtures covering observation identity, score semantics,
units, complete failure/censoring denominators, dependence groups, and explicit
resampling plans. The latency estimand is candidate p95 minus baseline p95,
not p95 of paired differences. Bounds alone do not establish calibrated 95%
coverage. The PR's reported native calculation speedup is not evidence of CO
routing speed, answer quality, or user waiting-time improvement.

Read-only Edge DOM and full-page visual inspection of RankWeave's Advanced
Security settings showed `Dependency graph` with an `Enable` button. No
settings were changed. This supplements dependency-review HTTP 403 evidence;
it is separate from the inspected CodeQL wrapper's successful dispatch with a
pending canonical verdict. Neither finding authorizes a gate bypass, and
neither constitutes a package-vulnerability finding.

### Historical implementation checkpoints

Child `eccb8328d484f41800f2dad27507c5dd9155165b` preserves locked observations
and removes count/completion-based routing recommendations. Its local full
regression finished with 3602 passed and two optional-dependency skips. This
is software regression evidence, not any of the four product claims above.

Child `c96be35382ba600dc36171b445ad49c50f61883d` subsequently clears 19 Ruff
findings in three benchmark paths while preserving system-local evidence dates.
Its focused 157 tests, benchmark statement/branch coverage and public docstrings
pass; its new hosted full/security checks were still in progress when recorded.
Neither predecessor's tests verify a later document or source revision.

At the preceding source revision, the reasoning-effort helper accepts a declared measured report
with baseline RMSE 1.0, candidate RMSE 0.1 and robustness=true, even with an
explicit synthetic origin. Changing only the labels on the default synthetic
ablation did **not** produce acceptance. No production-default mutation by the
helper was observed. That fixed 55% threshold was an independent
decision-contract gap; the benchmark repair did not resolve it.

## Default-promotion capability repair (Proposed)

Test-first commit `31ecc698` adds six cases: omitted, synthetic and claimed-live
origin, each with candidate RMSE zero or 0.1 against baseline 1. All six failed
against the old helper (0.68 seconds). These unit reports reproduce declaration
acceptance, not an actual deployment or a measured model comparison.

The follow-up removes the fixed threshold and retains the Boolean entry point
with the same report argument, returning false for all reports. The removed
`PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD` export and formerly true results are
intentional compatibility changes. Role configuration, provider propagation,
and route/conduct defaults are unchanged. CLI help and current documentation
now state that automatic promotion is unavailable.

This closes unsupported authority, not the full experimental requirement.
The synthetic estimator remains a deterministic unit fixture, not a released
psychometric estimator or measured effort effect. A decision capable of
authorizing deployment still needs the prospective evidence contract above,
the canonical statistical owner and independent operational acceptance.
No origin-label blacklist, replacement cutoff, new statistical kernel or
provider call is introduced. Historical numeric-validation receipts remain
historical; they no longer describe the callable's current decision behavior.

Rejected shortcuts are a different fixed sample cutoff, changing a report's
measurement label, treating prediction RMSE as latent-parameter recovery,
or treating green tests as evidence of buyer accuracy. The next implementation
must bind collection and decision claims to the prospective design above and
produce real held-out outcomes before an operational recommendation is made.
