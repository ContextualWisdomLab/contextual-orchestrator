# ADR-0100: Auto routing is quality-first and known-cost-second

- Status: Accepted
- Date: 2026-08-16

## Context

The public API already defaults to `auto`, which chooses a direct route for tasks judged simple enough and a conducted workflow for tasks requiring decomposition or verification. Within either path, worker selection used task-specific role/domain capability, operator priority, tag breadth, and a deterministic identifier tie-break. Configured model prices were available for spend reporting but did not influence quality-equivalent worker selection.

This allowed an expensive worker to win an otherwise exact capability tie solely because of its identifier. It also created a dangerous ambiguity: an absent or malformed price could be interpreted operationally as if it were zero.

## Decision

`auto` uses a lexicographic objective:

1. maximize task-specific capability and evaluated routing evidence;
2. among quality-equivalent candidates, prefer a candidate with trustworthy known price metadata;
3. among those candidates, minimize the configured nonnegative price proxy;
4. use the deterministic identifier only after quality and cost evidence tie.

A lower-capability model never wins merely because it is cheaper. Missing, nonnumeric, boolean, negative, NaN, or infinite price metadata is classified as unpriced, not free. An explicit zero price is valid known-price evidence.

The current implementation uses the operator-provided per-million-token price map as a deterministic routing proxy. It does not claim that this proxy is an invoice or that heuristic capability scores are a learned reward model. The existing evaluation/Pareto optimizer remains the path for calibrating priorities and candidate pools from measured quality, latency, and cost evidence.

## Consequences

Simple tasks still avoid unnecessary multi-agent compute. Complex tasks still receive deeper orchestration when the quality heuristic requires it. Within the selected quality tier, known lower cost becomes the deterministic tie-break. Routing policy snapshots expose the objective and the unpriced-model rule for audit and replay.

## References

Omidvar, H., & Akhlaghi, V. (2026). *A communication-theoretic framework for LLM agents: Cost-aware adaptive reliability* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2605.09121

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H., Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., & Clanuwat, T. (2026). *Sakana Fugu technical report* [Technical report]. arXiv. https://doi.org/10.48550/arXiv.2606.21228
