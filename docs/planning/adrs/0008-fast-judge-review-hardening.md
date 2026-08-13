---
id: "0008"
title: "Harden the fast-mlsirm contextual judge after review"
status: accepted
proposed_date: "2026-08-11"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "fast-mlsirm CodeRabbit review"
  - "fast-mlsirm judge and IRT callers"
informed:
  - "contributors"
affected_components:
  - "fast-mlsirm/python/fast_mlsirm/llm_judge.py"
  - "fast-mlsirm/python/fast_mlsirm/irt_contract.py"
  - "fast-mlsirm/tests/test_llm_judge.py"
  - "fast-mlsirm/tests/test_irt_contract.py"
  - "fast-mlsirm/README.md"
effort: S
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0005-irt-response-matrix-contract.md"
    relation: influenced-by
  - path: "docs/planning/adrs/0006-polytomous-llm-judge-bias-calibration.md"
    relation: influenced-by
  - path: "docs/planning/adrs/0007-sast-transport-and-sql-hardening.md"
    relation: influenced-by
asr_triggers:
  - kind: security
    evidence: "Review found predictable prompt delimiters around untrusted judge input, substring extraction that accepted wrapped model output, malformed public result mappings that could break IRT projection, and an unbounded criteria iterable."
    note: "Keep model-controlled content data-only, require one complete JSON value, validate mapping boundaries before sorting or set comparison, and bound iterable consumption."
  - kind: maintainability
    evidence: "Review found inconsistent exception types, coercive mapping normalization, mutable ADR links, and missing malformed-output tests."
    note: "Make the public contract explicit, use documented ValueError validation for malformed criterion inputs, reject conversion-hook numeric subclasses, and pin documentation to immutable evidence."
success_criteria:
  - metric: "judge trust-boundary validation"
    target: "untrusted task/answer/reference data is serialized as JSON, malformed model fields raise JudgeFormatError, and criterion inputs reject invalid runtime types with documented ValueError failures"
    measurement_window: "every fast-mlsirm judge test and PR review"
    source: "tests/test_llm_judge.py and CodeRabbit review"
  - metric: "IRT-safe projection"
    target: "dichotomous and polytomous rows contain only validated categories and retain the multi-item contract"
    measurement_window: "every judge-to-IRT conversion"
    source: "tests/test_llm_judge.py and tests/test_irt_contract.py"
  - metric: "documentation reproducibility"
    target: "ADR links resolve through an immutable contextual-orchestrator commit"
    measurement_window: "every README review"
    source: "fast-mlsirm README"
---

# Harden the fast-mlsirm contextual judge after review

## Context

The first fast-mlsirm PR added a provider-neutral judge routed through
contextual-orchestrator and a multi-item IRT projection. Its automated review
then identified several small but real weaknesses: model-controlled missing
fields escaped as generic `ValueError`, direct `LLMJudgeResult` construction
could project a negative category, malformed public result mappings could fail
before the intended `JudgeFormatError`, criteria iterables were not bounded
during consumption, mapping inputs were silently coerced, and predictable
XML-like prompt tags could be closed by answer text. The same review also found
unpinned ADR links and missing failure-path coverage.

> The review found two actionable comments and additional lint, test, prompt-boundary, and documentation findings.
>
> The user requires every plausible problem to become an explicit remediation direction, not a keyword or positional fallback.
>
> The fast-mlsirm PR must continue through review, remediation, re-test, and exact-head merge rather than stopping at a green local run.

## Decision Drivers

* Keep the contextual-orchestrator-only LLM-as-a-Judge path strict and fail closed.
* Prevent untrusted evaluation text from changing prompt structure.
* Preserve the dichotomous-or-polytomous multi-item IRT contract.
* Provide an ordinal polytomous path that does not rely only on one K-way score-ID choice.
* Make type, exception, test, and documentation behavior reproducible.

## Considered Options

* Treat review comments as optional style suggestions and keep the implementation.
* Add broad schema and prompt dependencies for the judge boundary.
* Apply small stdlib-only validation, JSON serialization, explicit error translation, and focused tests.

## Decision Outcome

Chosen option: "Harden the existing provider-neutral judge with small explicit boundary checks".

| Driver | Defer review findings | Add broad dependency | Explicit validation and focused tests |
| --- | --- | --- | --- |
| Model-output fail-closed behavior | Inconsistent | Depends on schema runtime | Preserved with `JudgeFormatError` |
| Prompt data boundary | Predictable tags remain | More operational surface | JSON payload with system-level data instruction |
| IRT category safety | Negative direct scores can leak | Hidden in dependency | `_score` plus bounded category projection |
| Reproducibility and maintenance | Mutable links and weak tests | Higher dependency cost | Immutable links and targeted regression tests |

`JudgeCriterion` now rejects non-string identifiers/descriptions and non-numeric
weights without coercion or incidental exception leakage; malformed criterion
inputs use documented `ValueError` failures. IRT projection validates direct
criterion-score and category mapping boundaries before sorting or set
comparison, then keeps category indices within bounds while retaining the
requirement for at least two criteria. Criteria are bounded while the iterable
is consumed. Model-controlled answer and rationale failures are translated to
`JudgeFormatError`; the caller's task and answer validation remains ordinary
input validation.

The user prompt carries task, answer, reference, and rubric as one JSON data
object rather than predictable open/close tags. The system instruction still
requires the model to ignore instructions inside those values. Failure-path
tests cover missing answer, missing rationale, and non-mapping completions;
category-bound tests cover invalid `n_categories`; and import ordering plus
the test regex are kept lint-clean. The response parser now passes the complete
bounded answer to `json.loads` and rejects prefixes, suffixes, and Markdown
fences instead of extracting the first and last braces. README ADR links use
the immutable contextual commit that contains ADR 0005 and ADR 0006.

The follow-up polytomous path adds opt-in `category_method="cumulative_threshold"`.
With an explicit category count, the model returns one Boolean decision for each
ordered boundary of each criterion. The adapter rejects wrong-length,
non-Boolean, and false-then-true vectors, derives the category and weighted
score itself, and retains the existing exact-schema, contextual-orchestrator,
and multi-item IRT requirements. Direct K-way categories remain available for
compatibility but stay experimental until category-method and prompt-perturbation
calibration supports them.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Criterion fields could raise incidental `TypeError` or accept coercive mapping values. | Validate runtime types explicitly and stop string/float coercion in `_criteria`. | Implemented |
| Invalid public criterion field types exposed inconsistent `TypeError` failures. | Normalize malformed criterion field validation to documented `ValueError` failures and test both direct and mapping inputs. | Implemented |
| Numeric weight subclasses could execute a custom `__float__` hook during validation. | Accept only exact built-in `int`/`float` weights before conversion and test a hooked subclass remains uncalled. | Implemented |
| Direct criterion scores could produce a negative or non-integral IRT category. | Validate scores with the same bounded score contract and clamp the projection to the legal category range. | Implemented |
| Public result mappings could be non-mappings or have non-string keys, causing incidental `TypeError` during IRT projection. | Validate `criterion_scores` and `criterion_categories` mapping/key boundaries before sorting or set comparison and fail with `JudgeFormatError`. | Implemented |
| A caller-controlled criteria iterable could exceed the configured maximum before validation completed. | Enforce `MAX_JUDGE_CRITERIA` during iteration, before normalizing an additional value. | Implemented |
| Missing model answer/rationale used generic `ValueError`. | Translate model-controlled bounded-text failures to `JudgeFormatError`. | Implemented |
| Predictable XML tags could be closed by untrusted answer text. | Serialize evaluation inputs as one JSON data payload. | Implemented |
| Response parsing extracted a brace-delimited substring and accepted wrappers/fences around model JSON. | Parse the complete bounded answer as exactly one JSON object and reject any surrounding text or Markdown fence. | Implemented |
| The fast adapter's `json.loads` accepted duplicate object members with last-value-wins semantics and ignored unknown top-level fields, weakening the strict judge contract. | Parse with a duplicate-rejecting `object_pairs_hook`, require the exact mode-specific top-level field set including the advisory boolean, and add top-level plus nested duplicate/unknown-field regressions. | Implemented on fast-mlsirm follow-up branch; retain exact-schema tests |
| Parsed advisory `accepted` name was overwritten by derived acceptance. | Rename the advisory field and derive acceptance only from the validated score. | Implemented |
| Public export order and a regex assertion were lint-fragile. | Reorder `__all__` and escape the literal test pattern. | Implemented |
| Invalid `n_categories` and malformed completion paths lacked tests. | Add focused `pytest.raises` coverage and preserve the multi-item checks. | Implemented |
| README ADR links targeted mutable/nonexistent `main` paths. | Pin links to the immutable contextual-orchestrator commit containing the referenced ADRs. | Implemented |
| A polytomous K-way choice can expose the judge to score-ID and category-count effects. | Add an opt-in cumulative-threshold mode with explicit K, exact criterion IDs, Boolean boundary vectors, monotonicity validation, derived categories, and focused IRT-row tests. | Implemented on fast-mlsirm follow-up branch; exact-head review pending |
| Threshold output can be syntactically valid but ordinally incoherent, or can disagree with direct K-way output. | Fail closed on non-monotone thresholds and record category method, K, score, acceptance, parse status, trace, and token usage in paired MLX calibration runs; do not claim bias removal. | Implemented in adapter/tests and 2026-08-12 exploratory run; calibration ongoing |
| The 2026-08-14 paired 3B probe showed direct scores rising with K for a safe case (`0.5 -> 1.0 -> 1.0`) and for an unsafe case at K=7 (`0.0 -> 0.0 -> 0.3333`); cumulative parsing/monotonicity failures remained 4/6. | Keep direct and cumulative methods experimental; add the bounded `binary_threshold` method as a fail-closed calibration probe, record its extra calls/tokens/latency and semantic misses, and require held-out human/gold agreement before changing a default. Never use keyword, positional, or silent repair. | Goal expanded 2026-08-14; binary method implemented on fast-mlsirm exact follow-up, calibration ongoing |
| The cached local Llama 3B judge failed strict structured parsing in 7/18 good-plan calls, including invalid JSON, an out-of-range category, and a non-monotone threshold vector; framing also shifted some K=7 scores. | Keep failures in the reliability denominator and test any bounded retry or stronger local-judge selection as a separate contextual-orchestrator experiment. Never repair by keyword/position or silently omit a failed call. | Recorded in 2026-08-12 benchmark; required calibration follow-up |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A model treats JSON string content as instructions despite the data boundary. | medium | high | Keep the system instruction explicit, never use model output as executable content, and review perturbation results. | maintainer |
| Clamping masks a caller-created invalid score. | low | medium | `_score` rejects non-finite/out-of-range values before the bounded projection; production results still originate from strict judge parsing. | maintainer |
| Immutable documentation ref becomes hard to update. | low | low | Add a new pinned link when the contextual ADR set changes; do not return to mutable `main` links. | documentation owner |

## Rollback / Exit Strategy

If a downstream caller depends on coercive criterion values, migrate that caller
to explicit `JudgeCriterion` construction rather than restoring silent coercion.
If a future structured message API is introduced, retain the JSON data contract
or an equivalent typed payload and keep `JudgeFormatError` as the fail-closed
boundary. Do not restore keyword matching, positional repair, or one-item IRT
conversion.

## Affected Components

* fast-mlsirm/python/fast_mlsirm/llm_judge.py
* fast-mlsirm/python/fast_mlsirm/irt_contract.py
* fast-mlsirm/tests/test_llm_judge.py
* fast-mlsirm/tests/test_irt_contract.py
* fast-mlsirm/README.md
