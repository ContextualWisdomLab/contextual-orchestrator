# ADR 0100: Capability first, known cost second

## Status

Accepted for the main-line first slice. Aligns with open PR #575. Quality/Pareto
beyond tags is issue #86 and is explicitly deferred.

## Decision

`TaskOrchestrator._ranked_agents` sorts lexicographically:

1. existing capability score (role tags × 3 + domain hints × 2 + priority);
2. whether a finite nonnegative `price_per_million` exists;
3. lower known price;
4. tag count (stability only — catalog tag inflation is not a capability win);
5. agent id.

Unknown, boolean, nonnumeric, negative, NaN, and infinite prices are unpriced,
never free. Explicit channel zero with **no** list/original price is a valid
known price of 0. A model served free that still has a catalog list price,
published $/1M, or finite OpenRouter `pricing` (including a same-document paid
`:free` sibling) is compared at that original price — it does not win as cost
0.0. A list price is never fabricated. `cheapest_upstream` is not used because
it treats unpriced as cost 0.0.

Failover / circuit breaker still walk the ranked tail after the chosen primary
errors. They are not the way the primary is chosen.

## Consequences

A cheap summarizer cannot beat a coding worker on a coding task. Among
capability-equivalent priced workers, the cheaper known price wins. Unpriced
peers lose a cost comparison. Paper contracts (Fugu route/conduct, Trinity
roles, Conductor access lists) stay on the same capability heuristic.

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance*. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan,
L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM: Cost-efficient and
quality-aware query routing*. arXiv. https://doi.org/10.48550/arXiv.2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data*. arXiv. https://doi.org/10.48550/arXiv.2406.18665

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110
