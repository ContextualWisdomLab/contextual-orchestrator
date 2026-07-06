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
