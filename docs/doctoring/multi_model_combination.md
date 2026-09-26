# Multi-model combination foundation

Status: Proposed (2026-09-26). Implements a conflict-free slice of
[ADR 0124](../adr/) step 4 (combination domain) while step 1
(PR #1262) and steps 2–3 are in flight.

## Gap on `main` (`5665b0ad`)

The product's purpose is to raise answer quality by combining models (Sakana
Fugu; see [architecture](../architecture.md)). On `main`, no request path
combines two models' *answers*:

- `route_once` returns one worker's answer; judge rejection triggers
  sequential failover to the next-ranked worker (`orchestrator.py:9171-9241`).
- `conduct` assigns exactly one worker per plan (`orchestrator.py:9467-9483`)
  and the synthesizer only sees that single worker's output through the
  access list.
- `nim_benchmark.evaluate_policies` compares route, conduct, and direct
  single workers; it has no arm in which several workers answer the same task.

So the "combination beats the best single model" claim cannot currently be
tested, let alone achieved.

## What this change adds

| Module | Role | Source | Divergence |
| --- | --- | --- | --- |
| `domain/candidates.py` | `CandidateAnswer`, `CandidateSet`, `CombinationOutcome` value objects | — | — |
| `domain/combination.py` `RankedFirst` | Today's route semantics as a strategy | — | — |
| `domain/combination.py` `PluralityVote` | Vote over extracted final answers; agreement share reported as `support` | Wang et al. (2023), arXiv:2203.11171 §2, §3.5 | Voters are different workers, not samples of one model. Only a unique plurality is selected; a tied plurality abstains (`plurality_tie`). No support threshold is applied. |
| `domain/combination.py` `ScoredBestOfN` | Pick the unique highest score from an external scorer port; an exact top-score tie abstains (`score_tie`) | — | Rank is not scorer evidence. Wang et al. (2024) find an LLM ranker weaker than MoA aggregation (§3.3); kept as a baseline arm. |
| `domain/moa.py` | Aggregate-and-Synthesize aggregator messages | Wang et al. (2024), arXiv:2406.04692 Table 1, Eq. 1 | One proposer layer (MoA-Lite depth). Proposers anonymised. "open-source models" → "models". |
| `application/fan_out.py` | Parallel fan-out through a bounded-concurrency completion port; MoA runner | — | `deadline_seconds` defaults to `None`, so upstream completion owns termination. A finite value is an explicit administrative bound for the proposer layer only. |

Fail-closed rules, consistent with planning ADR 0001:

- No heuristic decides between answers: prior rank never breaks a vote or
  score tie; ties abstain. Rank only picks the representative text among
  candidates that already agree on the same extracted answer.
- A strategy that lacks evidence abstains (`selected is None`); it never
  invents or silently substitutes an answer.
- Provider error messages are never recorded; only the exception class name.
- Cost is `None` whenever any part is unknown, including when a proposer
  failed (a failed call may still be billed).
- A vote-count tie or external-score tie abstains. Rank is evidence ordering,
  not an uncalibrated secondary quality score.
- No support threshold is accepted. The cited plurality rule selects only a
  unique mode; an unsupported policy threshold cannot change admission.
- Fan-out has no default elapsed-time cutoff. A finite deadline is explicit
  administrative input, while the completion port owns upstream cancellation.

## 2026-09-27 no-heuristics repair

Exact head `a4183535` required every caller to invent a finite
`deadline_seconds`, accepted an arbitrary plurality `min_support`, and used
prior rank to decide both vote-count and score ties. The module documentation
identified the first two plurality controls as repository choices rather than
results of the cited self-consistency algorithm.

RED commit `e34a038b` adds contracts for default-null completion, tied-mode
abstention, unique-plurality selection without a threshold, and score-tie
abstention. GREEN commit `0940e654` removes the unsupported controls. The
focused combination/fan-out suite passes 58 tests. This evidence is PR-head
only until exact-head hosted checks and independent approval complete.

## Evidence boundary

- `tests/test_combination_domain.py::test_plurality_vote_mechanism_beats_best_single_on_independent_errors`
  shows the *mechanism* on synthetic, independent-error workers (Condorcet).
  It is not evidence that real providers, whose errors correlate, gain.
- The product claim requires a live paired evaluation: add `plurality_vote`
  and `mixture_of_agents` arms to `nim_benchmark.evaluate_policies` and compare
  against `best_single_worker_hindsight` with
  `paired_bootstrap_mean_difference`. That wiring touches `nim_benchmark.py`
  and, for serving, `TaskOrchestrator`; it follows after PR #1262 and ADR 0124
  step 2 land.
- The modules import no IO and not `orchestrator`
  (`tests/test_domain_import_boundary.py`). Importing them still loads
  `orchestrator` through the package `__init__` until step 2 makes it lazy.

## Reproduction

```bash
python -m pytest -q tests/test_combination_domain.py tests/test_fan_out.py \
  tests/test_domain_import_boundary.py tests/test_docstring_coverage.py
```
