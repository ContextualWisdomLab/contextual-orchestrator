# ADR 0100: Capability first, known cost second

## Status

Accepted for the main-line first slice. Aligns with open PR #575. Quality/Pareto
beyond tags is issue #86 and is explicitly deferred.

## Decision

`TaskOrchestrator._ranked_agents` sorts lexicographically:

1. existing capability score (role tags × 3 + domain hints × 2 + priority);
2. tag count;
3. whether a finite nonnegative `price_per_million` exists;
4. lower known price;
5. agent id.

Unknown, boolean, nonnumeric, negative, NaN, and infinite prices are unpriced,
never free. Explicit zero is a valid known price. `cheapest_upstream` is not
used because it treats unpriced as cost 0.0.

Failover / circuit breaker still walk the ranked tail after the chosen primary
errors. They are not the way the primary is chosen.

## Consequences

A cheap summarizer cannot beat a coding worker on a coding task. Among
capability-equivalent priced workers, the cheaper known price wins. Unpriced
peers lose a cost comparison. Paper contracts (Fugu route/conduct, Trinity
roles, Conductor access lists) stay on the same capability heuristic.
