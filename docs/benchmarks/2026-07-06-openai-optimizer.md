# Measured: auto-optimizer on real OpenAI (2026-07-06)

One measured run of `evolve_orchestration` against live `api.openai.com` (verified TLS),
searching orchestration configs for **maximum quality at minimum cost**. This is a small,
single-run measurement — method and caveats below; not a general quality claim.

## Method

- **Search space (6 configs):** `mode ∈ {route, conduct}` × `model ∈ {gpt-4.1-nano, gpt-4.1-mini, gpt-4o-mini}`.
- **Search:** `evolve_orchestration`, seeded (seed=7), generations=3, population=4 — evaluated **5 of 6** configs (dedup cache; each config paid for once).
- **Tasks (24, checkable):** trick arithmetic (bat-and-ball, widgets, lily pads), letter/digit counting, unit conversion, logic traps. Scoring: exact expected number appears in the reply (`quality_fn` returns 0/1 per task; quality = mean).
- **Cost:** provider-reported `usage` via the engine's spend analytics; prices are **approximate public USD/1M output tokens** (nano 0.40, 4o-mini 0.60, mini 1.60) supplied as the operator price table.
- **Wall time:** 238.6 s, sequential calls.

## Results

| mode | model | quality (24 tasks) | measured cost | quality/$ |
|---|---|---|---|---|
| **route** | **gpt-4.1-nano** | **0.792** | **$0.000011** | 71,970 |
| conduct | gpt-4.1-nano | 0.792 | $0.001029 (94×) | 769 |
| route | gpt-4o-mini | 0.750 | $0.000016 | 46,875 |
| route | gpt-4.1-mini | 0.750 | $0.000043 | 17,442 |
| conduct | gpt-4o-mini | 0.667 | $0.000820 | 813 |

- **Pareto front:** `route/gpt-4.1-nano` alone — it dominates every other evaluated config.
- **Recommendation (max quality, min cost):** `route/gpt-4.1-nano` — "highest quality; cheapest among equal-quality configs".
- The evolutionary search converged on the winner in generation 0 and held it (small space; the value of `evolve_orchestration` is the same loop on spaces too large to enumerate).

## Honest findings

1. **Orchestration did not improve quality on these tasks.** `conduct` (thinker→worker→verifier→synthesizer) matched `route` at best (nano: same 0.792 for 94× the cost) and was *worse* for 4o-mini (0.667 vs 0.750 at 51× the cost). For short checkable questions, the multi-step pipeline mostly adds cost and opportunities to reformat the answer wrongly.
2. **The bigger model did not win either** — gpt-4.1-nano beat gpt-4.1-mini/4o-mini on this set. Small samples (24 tasks, single run) can produce such inversions; treat the *ranking* as noisy, the *cost ratios* as robust.
3. This is exactly why the optimizer exists: **measure per workload instead of assuming** "orchestrate more / buy the bigger model".

## Caveats

- Single run, 24 tasks, one seed — no confidence intervals; answer-format scoring is strict (a correct answer phrased without the bare number scores 0).
- Task types (short checkable questions) are favorable to `route`; long decomposition/verification workloads may favor `conduct` — unmeasured here.
- Prices are approximate list prices, not billed amounts; tokens are provider-reported usage.
- Reproduce: `evolve_orchestration(build, SPACE, TASKS, quality_fn, generations=3, population=4, seed=7)` with an `OPENAI_API_KEY`; the harness lives in the engine, the task list in this document's history.

## Batch API smoke (real endpoint, 2026-07-06)

One real `TaskOrchestrator.batch_route` run against live `api.openai.com` Batch API
(2 requests, gpt-4.1-nano): upload → batch create → poll → parse.

- **Wall time:** 131.3 s end-to-end (the async Batch queue dominates; fine for eval
  workloads, confirms it is wrong for interactive chat).
- **Answers:** `"4"` (2+2) and `"Paris"` — both correct.
- **Usage:** provider-reported per line (prompt 20/19, completion 1/1) and threaded
  into spend analytics: `prompt_tokens_source=reported`, `reported_prompt_tokens=39`,
  run_count 2, estimated cost $0.000001 at the nano list price.
- Caveat: cost is computed at the list price table; the Batch ~50% discount is a
  provider billing property not reflected in the operator price table unless the
  operator supplies batch-specific prices.

## Generated-workflow validation (Conductor, real endpoint, 2026-07-06)

One real `conduct()` with `workflow_planning="generated"` (gpt-4.1-mini as planner and
workers): the model **generated a valid Conductor-style plan** — 4 steps with
natural-language subtasks and non-template access lists (e.g. the synthesizer accessed
`[1, 2]`, not the fixed template's `[0, 1, 2]`) — which parsed, validated, and executed
end-to-end in 48.2 s, producing a coherent rollback-safe migration plan.

- `plan_source=generated`; strict validation (sequential ids, known roles,
  backward-only access, answerable final step) with automatic template fallback held.
- Honest limitation observed: `verification.accepted=false` because the term-matching
  verifier judge saw risk-vocabulary in a verifier step *about* downtime risks — a
  false negative of the heuristic judge, not of the plan. **Fixed since:** `OrchestrationPolicy.verifier_judge="model"` asks a verifier-selected model to reply ACCEPT/REJECT on the verifier report (ambiguous replies and judge failures keep the term verdict; default remains "terms").
- This validation exercised `conduct()` directly (not `run()`), so it does not appear
  in spend totals.
