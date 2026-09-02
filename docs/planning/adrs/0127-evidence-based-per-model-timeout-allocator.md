# ADR 0127: Per-Model Latency Measurement Without Heuristic Timeout Allocation

- Status: Proposed
- Date: 2026-09-02
- Responds to: `contextual-orchestrator#1010`
- Governs alongside: `contextual-orchestrator#971`, ADR 0021, ADR 0033, ADR 0034
- Related organization contract: `ContextualWisdomLab/.github` ADR 0003

## Problem

`contextual-orchestrator#1010` introduced an admin-editable per-model timeout with repository-authored minimum and maximum values. The repository owner closed that lane because those bounds were selected by analogy rather than by an identified statistical, experimental, standards-based, or research-backed decision model.

The follow-up draft of this ADR repeated the same class of defect in a subtler form: it proposed fixed sample-size floors, a fixed raw-sample retention count, percentile-class-specific estimator switching, a data-dependent Peaks-Over-Threshold threshold example, and a fallback ladder that pooled a model with a coarser provider/profile aggregate when direct evidence was sparse. Those rules affected whether a timeout number would be surfaced, yet the repository had no fitted decision model proving those exact constants or fallback relations. Under the ContextualWisdomLab no-heuristics contract, those rules are not admissible.

The correct owner-side response is therefore not to choose better-looking constants. The repository must separate **measurement** from **timeout decision authority**. It may estimate latency distributions and uncertainty using explicit statistical models with executable provenance. It must not convert those estimates into a repository-authored timeout recommendation until a separate loss/utility model, standard, or validated experimental decision rule identifies that action.

## Current evidence boundary

Protected code already measures elapsed time at several request paths, but the repository does not retain a complete, queryable latency sample suitable for reproducible distributional inference. Existing EWMA latency state and static route-p95 display/default values are not substitutes for a retained statistical sample, and they must not be promoted into timeout authority.

Consequently, this ADR is **not executable against live traffic today**. Any implementation must begin with exact observation retention and provenance. Until then, the default application/Agent/Gateway model timeout remains `null` under the standing ContextualWisdomLab contract, and provider termination, explicit caller/operator cancellation, and independently configured administrative timeout state remain distinct events.

## Decision

### 1. Measure; do not recommend a timeout automatically

The first released surface governed by this ADR is a latency-measurement surface. It reports estimates, uncertainty, censoring, and provenance. It makes **no automatic timeout recommendation**.

The output contract therefore uses fields such as:

```json
{
  "target_quantile_probability": 0.95,
  "quantile_seconds": null,
  "confidence_interval_seconds": null,
  "method": "kaplan_meier_brookmeyer_crowley",
  "observation_count": 0,
  "completed_count": 0,
  "right_censored_count": 0,
  "analysis_window": null,
  "provenance_digest": null,
  "suggested_timeout_seconds": null
}
```

The numeric example above illustrates schema shape only; it is not a repository default or an admission threshold. `target_quantile_probability`, confidence level, analysis interval, and any later decision-model inputs must be explicit caller/operator-supplied analysis parameters and recorded in provenance. The software supplies no hidden defaults that alter a decision.

If the requested estimand is not mathematically identifiable from the supplied observations, the corresponding estimate is `null`. The system must fail closed rather than pool another population, change the target percentile, invent a tail model, or substitute an arbitrary constant.

### 2. Retain exact observations with provenance

A prerequisite implementation shall persist one observation per governed model request using a durable schema that can reconstruct the analysis population. At minimum it records:

- immutable request-observation identity;
- provider and concrete model identity as served, not inferred from names;
- request start and terminal timestamps from the same monotonic timing boundary used to compute duration;
- terminal state such as completed, provider-ended, caller-cancelled, administrator-timeout, transport-failed, or otherwise explicitly classified;
- time to first token when actually observable on streaming paths;
- declared reasoning/test-time-compute profile identity when supplied by the governed request contract;
- exact contextual-orchestrator version/source identity and analysis-schema version; and
- privacy-safe provenance sufficient to reproduce the statistical population without storing prompt, response, credential, or other secret material.

This ADR defines no magic rolling sample count and no repository-authored age cutoff for statistical validity. Retention is a separate storage/privacy/governance policy. Every statistical result binds the exact included observation identities and analysis interval so the result is reproducible regardless of the operational retention mechanism.

### 3. Completed uncensored observations use an explicit empirical quantile model

For a population with no censoring relevant to the requested latency estimand, define the empirical distribution function

\[
F_n(t)=\frac{1}{n}\sum_{i=1}^{n} I(T_i\le t)
\]

and the empirical quantile

\[
Q_n(p)=\inf\{t:F_n(t)\ge p\}.
\]

No fixed `n` floor controls whether the estimate exists. The estimate and its uncertainty are reported from the mathematical model for the exact observed sample.

When a distribution-free confidence interval for a population quantile is requested, its order-statistic indices are derived from the exact Binomial\((n,p)\) distribution for the caller-supplied confidence level. The implementation records `n`, `p`, confidence level, selected order-statistic indices, and the exact observations used. There is no repository-authored p50/p90/p95/p99 sample table and no hand-written switch that silently changes estimator families.

If the requested confidence interval cannot be represented because the finite sample does not support the requested order-statistic bounds, the interval is `null`; the system does not manufacture a narrower interval or borrow another population.

### 4. Censored latency uses survival analysis, not completed-only deletion

A request that is externally terminated before natural model completion is not an ordinary completed latency observation. Treating it as if it completed at the termination time, or dropping it from the population, changes the estimand.

For right-censored time-to-completion data where the independent-censoring assumptions are documented and testable for the analysis design, use the Kaplan–Meier product-limit estimator for the completion-time survival distribution. Quantile confidence intervals use the Brookmeyer–Crowley inversion method or a documented mathematically equivalent survival-quantile procedure.

The implementation must report censoring counts and terminal-reason strata. If the target quantile is not identifiable because the estimated survival curve does not cross the requested probability before the last supported event time, the quantile and its interval are `null`. No timeout value is inferred from the censoring boundary.

If independent censoring is not defensible for the requested analysis—such as when an existing budget deterministically truncates difficult reasoning runs—the Kaplan–Meier result is not promoted as an unbiased population latency estimate. The analysis must instead use a separately specified model appropriate to that censoring mechanism or fail closed.

### 5. No cross-model/provider fallback without a fitted hierarchical model

Sparse evidence for one model does not authorize an informal ladder such as `model -> reasoning profile -> provider -> global`.

Pooling or partial pooling across models/providers is permitted only when a separately documented statistical model defines the shared population structure, its exchangeability assumptions, fitted parameters, uncertainty, diagnostics, and validation evidence. A hierarchical survival model, for example, could become such an owner if its assumptions and predictive validation were executable. This ADR does not define one.

Therefore the current fallback order is mathematically empty: if the requested model-specific estimand is not identified from its governed population, return `null`.

### 6. No EVT/POT tail extrapolation without an identified threshold-selection procedure

Extreme-value Peaks-Over-Threshold methods are legitimate research-backed models, but their result depends materially on threshold selection and diagnostics. An example such as “use empirical p90” is not a threshold-selection algorithm and is prohibited as a decision rule.

A future EVT slice must specify an executable threshold-selection and model-checking procedure, bind its assumptions and uncertainty, and validate it against held-out or simulation evidence appropriate to the deployment population. Until such a model exists, this ADR performs no tail extrapolation.

### 7. TTFT/TPOT remains diagnostic evidence only

Time-to-first-token, inter-token timing, output length, and full completion duration may be retained as diagnostic observables. They do not become a timeout formula merely because they are measurable.

For reasoning/test-time-compute profiles, the system reports completion and non-completion outcomes with uncertainty rather than imposing a model-name rule, convergence percentage cutoff, or elapsed-time stop policy. Any model-backed compute-allocation policy remains owned by contextual-orchestrator's research-backed routing/test-time-compute layer and must be justified independently by its Fugu/Conductor/TRINITY-or-successor evidence.

### 8. Timeout action requires a separate identified decision model

A timeout is an action, not a descriptive statistic. Choosing one trades off at least completion probability, answer quality, cost, latency, cancellation harm, and downstream operational risk. A latency quantile alone does not identify that trade-off.

A future automatic suggestion is admissible only if a separate ADR defines an explicit loss/utility function or authoritative external standard, the estimable quantities entering it, the optimization rule, uncertainty propagation, calibration/validation experiment, and provenance. For example, a decision-theoretic rule could choose

\[
t^*=\arg\min_t E[L(t,Y,C,Q,\ldots)]
\]

only after `L` and the joint outcome model are actually specified and validated. Without that owner, `suggested_timeout_seconds` remains `null`.

An operator may still explicitly configure an administrative timeout through the governed admin API. That is an explicit operator decision and must be audited as such; the measurement service must not mislabel it as statistically recommended.

## Security, privacy, and audit requirements

- Never persist credentials, prompts, responses, raw tool payloads, or secret-bearing headers in latency observations.
- Redact provider error material before durable persistence unless an independently governed secure evidence store is explicitly referenced by digest/ID.
- Bind every analysis result to exact observation IDs, analysis parameters, software/source version, method identifier, and deterministic provenance digest.
- Distinguish provider termination, caller cancellation, administrative timeout, transport failure, and model completion.
- A missing/malformed observation, impossible timestamp ordering, non-finite duration, unknown terminal state, or inconsistent provenance fails closed for that observation/result; it is never silently coerced.

## Required executable contracts before implementation can be promoted

The implementation PR must add RED-first tests where practical and then prove GREEN for at least:

1. exact empirical quantile calculation from retained uncensored observations;
2. Binomial-derived order-statistic confidence bounds with no fixed sample-size admission table;
3. Kaplan–Meier estimation and Brookmeyer–Crowley quantile intervals on right-censored fixtures with known expected values;
4. target quantiles that are not identifiable returning `null` rather than a fallback number;
5. no cross-model/provider pooling in the absence of a declared hierarchical model;
6. no EVT/POT extrapolation in the absence of a declared threshold-selection/model-checking algorithm;
7. distinct provider-end, caller-cancel, admin-timeout, and transport-failure provenance;
8. deterministic audit/provenance output;
9. malformed/non-finite/inconsistent observations failing closed; and
10. absence of any repository-authored automatic timeout recommendation when no separate decision model is configured.

Synthetic observations are permitted only in unit/statistical recovery tests. Production claims require real retained observations and exact-head evidence.

## Rejected alternatives

### Fixed sample-size floors

Rejected. Approximate tables may be useful educational summaries, but they are not an executable admission model for this deployment. The exact sampling distribution and resulting uncertainty are available from the stated statistical model and should be reported directly.

### Fixed raw-sample retention counts

Rejected as statistical authority. Operational retention may be bounded by explicit storage/privacy policy, but a round-number retention cap must not decide whether a timeout estimate is valid.

### Coarser aggregate borrowing

Rejected absent a fitted hierarchical model with validated exchangeability assumptions. Provider/profile labels alone do not prove that their latency distributions are interchangeable.

### Hardcoded percentile-to-estimator switching

Rejected. The initial implementation uses one explicit empirical/survival estimand and reports its uncertainty. Alternative estimators require their own identified model-selection evidence rather than percentile-name routing.

### Automatic timeout from an observed percentile

Rejected. Descriptive latency does not define the loss of terminating an unfinished model response. Without an explicit decision model, automatic timeout allocation is unidentified.

## Consequences

- `contextual-orchestrator` gains a statistically auditable latency-measurement path before it gains any automatic timeout allocator.
- Existing fixed timeout constants, static p95 labels, or EWMA state cannot be cited as recommendation evidence.
- Sparse or censored data can legitimately yield `null`; availability is not restored by heuristic fallback.
- The admin UI may display measured distributions, uncertainty, censoring, and explicit operator-configured timeout state while keeping the recommendation field null.
- A future allocator must be a real decision model with executable validation, not a renamed percentile rule.

## Follow-up

1. Repair any production route/latency labels that currently present hardcoded thresholds as measured facts.
2. Implement durable privacy-safe latency observations with exact provenance.
3. Add the statistical recovery tests above before exposing measurement in the admin API/UI.
4. Keep `suggested_timeout_seconds=null` until a separately reviewed decision model or authoritative standard identifies an automatic action.
5. Revalidate `contextual-orchestrator#971` and all model-backed ContextualWisdomLab Actions consumers after the owner contract is released immutably.

## References

Brookmeyer, R., & Crowley, J. (1982). A confidence interval for the median survival time. *Journal of the American Statistical Association, 77*(378), 433–440. https://doi.org/10.1080/01621459.1982.10477833

David, H. A., & Nagaraja, H. N. (2003). *Order statistics* (3rd ed.). Wiley.

Kaplan, E. L., & Meier, P. (1958). Nonparametric estimation from incomplete observations. *Journal of the American Statistical Association, 53*(282), 457–481. https://doi.org/10.1080/01621459.1958.10501452

Hyndman, R. J., & Fan, Y. (1996). Sample quantiles in statistical packages. *The American Statistician, 50*(4), 361–365. https://doi.org/10.1080/00031305.1996.10473566
