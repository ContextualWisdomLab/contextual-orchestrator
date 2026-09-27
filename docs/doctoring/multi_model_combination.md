# Multi-model combination: gap and reintroduction record

Status: Gap open (2026-09-27). A Proposed combination/fan-out surface was
added to PR #1267 and then withdrawn under review 5328347433, because it had
no selection authority. No combination code is present on this branch.

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

The claim that combining models beats the best single model is therefore
neither implemented nor measurable today.

## Why the Proposed surface was withdrawn

Review 5328347433 on PR #1267 found that the surface decided which model
answer to return without an authority for that decision:

- `RankedFirst` selected by caller-supplied rank, with no model.
- `PluralityVote` applied single-model self-consistency (Wang et al., 2023)
  to different workers, whose errors correlate; no live paired evidence
  existed.
- `ScoredBestOfN` accepted any float-returning callable, with no released
  schema, calibration identity, uncertainty, or provenance.
- `collect_candidates` / `mixture_of_agents` accepted caller-chosen proposer
  sets and concurrency without a Fugu/Conductor/TRINITY-compatible allocation
  receipt.

Tie abstention (`0940e654`) repaired a symptom but not the missing
authority. Because the surface was not wired into serving, removal is the
fail-closed outcome.

## Reintroduction conditions

A combination surface may return only when all of these exist (from review
5328347433):

1. An immutable owner contract for the selection decision.
2. Released fast-mlsirm evidence for any scorer used to choose between
   answers (schema, calibration identity, uncertainty, provenance).
3. A typed `no_decision` outcome instead of an implicit fallback.
4. Executable allocation and paired-evaluation acceptance: live paired arms
   in `nim_benchmark` against `best_single_worker_hindsight`
   (`paired_bootstrap_mean_difference`), and an allocation receipt for
   proposer sets and concurrency.

Known prerequisites outside this record:

- Live evaluation needs the production provider keys, which exist only as
  `production`-environment secrets usable from `main`; a `workflow_dispatch`
  paid/free canary on `main` is required (see the coordination note on PR
  #1263).
- ADR 0124 step 1 (PR #1262) and step 2 (ports/adapters) before serving
  wiring.
- PR #1209 for the `main`-side test and security gates.
