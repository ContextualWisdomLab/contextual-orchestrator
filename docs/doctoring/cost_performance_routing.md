# Cost-performance routing (APA 7)

This note states the **product selection policy** for
`route_once` / `/v1/chat/completions`. It replaces the former deterministic
keyword-scoring description in `docs/architecture.md`. Citations follow the
*Publication Manual of the American Psychological Association* (7th ed.).

## Claim boundary

| Claim | Boundary |
| --- | --- |
| One worker per fast-path request | Fugu selects a single worker for the low-latency path (Sakana AI, 2026). The gateway does not walk the seed JSON to “try the next name.” |
| Objective | Maximize expected quality per unit cost. Interactive requests also penalize measured latency when `latency_ms` already exists on traces (Ding et al., 2024). |
| Quality signal | TRINITY role-tag overlap (`ROLE_TAGS`: thinker / worker / verifier / synthesizer) (Zhang et al., 2025). When no candidate has role-tag overlap, every remaining healthy worker shares a documented prior of 1.0. Prompt keywords (`DOMAIN_HINTS`) are **not** a selection signal. |
| Cost signal | Operator `price_per_million` (the same table spend analytics uses). Missing or non-positive prices are **not** treated as free (Chen et al., 2023; Ong et al., 2024). If any priced capable worker exists, unpriced equivalents are excluded. If every capable worker is unpriced, unit cost is the documented prior 1.0 (quality-only). Prices are never invented. |
| Measured extras | Circuit-breaker failures scale success as `1 / (1 + failures)`. Latency penalty applies only on the interactive path and only from recorded traces. No eval-set coordinator is trained here. |
| Deep path | Conductor workflows (decompose / verify / synthesize with access lists) run only when the task needs them (Li et al., 2025). A review is not expanded into a multi-agent walk just to burn the pool. |
| Exceptions | 429 / 5xx / timeout: re-run the **same chooser** on the remaining healthy pool. Circuit-open agents are excluded. A worker with no resolvable KV credential is not a candidate. An empty healthy pool fail-closes. |
| Out of catalog | GitHub Models, `COPILOT_GITHUB_TOKEN`, `models.github.ai`, `gpt-5.6-luna`, and `gpt-5.6-terra` are never candidates. |

Tie-breaks are `(model, id)` after quality-per-cost. List index, seed order, and
`priority` do not decide the winner.

## Why this is not a list walk

FrugalGPT and Hybrid LLM motivate a **cheap capable path first**, then a
stronger path only when needed (Chen et al., 2023; Ding et al., 2024).
RouteLLM frames the same decision as a router over a pool, not a static
fallback order (Ong et al., 2024). Walking `agents[i+1]` after a 429 would
make seed-file order the policy. Re-selection keeps the objective when the
first choice is unhealthy.

## Priors when a signal is missing

| Missing signal | Prior | Fail-closed alternative |
| --- | --- | --- |
| No `price_per_million` for a model | Exclude that worker if any priced capable peer exists; else unit cost 1.0 | Do not invent a vendor list price |
| No role-tag overlap in the whole healthy pool | Quality 1.0 for every remaining healthy worker | — |
| No recorded `latency_ms` | Penalty 1.0 (no invented latency) | — |
| No eval-set quality | Role tags + circuit success only | Do not train a coordinator from empty logs |
| Empty healthy pool | — | `NotConfigured` / refuse; no GitHub Models |

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance*. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan,
L. V. S., & Hassan Awadallah, A. (2024). *Hybrid LLM: Cost-efficient and
quality-aware query routing*. In *Proceedings of the Twelfth International
Conference on Learning Representations*. https://doi.org/10.48550/arXiv.2404.14618

Li, Y., et al. (2025). *Learning to orchestrate agents in natural language with
the Conductor*. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data*. arXiv. https://doi.org/10.48550/arXiv.2406.18665

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Zhang, et al. (2025). *TRINITY: An evolved LLM coordinator*. arXiv.
https://doi.org/10.48550/arXiv.2512.04695

Redistributable arXiv PDFs already vendored under `docs/papers/` (FrugalGPT,
RouteLLM, Hybrid LLM) remain the cost/routing evidence pack. Fugu / TRINITY /
Conductor are cited by URL; they are not copied here.
