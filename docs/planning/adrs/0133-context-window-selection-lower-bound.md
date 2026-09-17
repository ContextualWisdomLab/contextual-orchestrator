# ADR 0133: Selection-time context-window lower bound vs exact shared-context budgeting

## Status

Accepted (2026-09-17)

## Context

Issue #940's tool-call capability exclusion already lands on `main` via #1170.
Two complementary gaps remain for review/free-pool reliability:

1. Pre-flight exclusion of virtual-selector candidates whose *known*
   `ModelAgent.context_window` cannot hold the prompt (#1178).
2. Treating provider HTTP 400 context-window overflow as a request-size
   rejection eligible for failover (#1174).

Shared-context output budgeting (#1157) deliberately refuses estimates: it
returns a decision only from provenance-bound exact message counts
(`describe_message_count`) plus known catalog windows. That exact-only rule
must not be weakened.

Selection-time exclusion needs a different honesty contract. Many free-pool
models lack a mapped native tokenizer, so requiring exact counts would leave
the filter inert for the pool that most needs it. Burning an attempt and
relying on the provider's 400 (even after #1174 classifies it) still wastes a
round-trip before the next candidate (Ong et al., 2024).

## Decision

Allow a *labeled* conservative lower bound exclusively for virtual-selector
candidate exclusion:

- Prefer `token_counter.count_text` when available (`source="exact"`).
- Otherwise use `estimate_lower_bound_tokens` (`source="estimate_lower_bound"`),
  a documented character-count heuristic that is biased to under-count and
  collapses long repeated-character runs so the bound does not overestimate
  tokenizer run folding.
- Exclude only when `context_window` is a known positive int strictly smaller
  than that bound. Unknown (`None`) windows never exclude.
- Never pre-filter an explicitly requested concrete model.
- Do **not** feed this estimate into shared-context budgeting, spend
  accounting, or fabricated usage.

## Consequences

- Pre-flight exclusion and exact budgeting stay separate seams with separate
  evidence labels.
- Over-exclusion of viable candidates is possible when the heuristic is loose;
  under-exclusion remains possible for adversarial text. Both are preferable
  to inventing an exact count or hardcoding pool/model limits.
- Complementary post-rejection failover (#1174) remains required when the
  bound cannot prove overflow (unknown window or underestimate).

## References

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* (arXiv:2406.18665).
