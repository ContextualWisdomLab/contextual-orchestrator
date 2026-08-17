# ADR 0002: Cost-aware routing

- Status: Accepted
- Date: 2026-08-16

## Context

Model cost and quality vary by orders of magnitude across providers. A gateway
that always calls the strongest model, or that always uses the interactive
sync path, cannot be the org cost-review hub. The product already claims a
spend ledger, a `RoutingPolicy`, and a sync-versus-batch split.

Three papers ground that claim:

- FrugalGPT shows that cascading and cost-aware model choice can cut spend
  while holding quality.
- RouteLLM treats routing itself as a learned (or at least explicit) decision
  between stronger and weaker models.
- Hybrid LLM separates easy/bulk queries from hard/interactive ones so the
  cheap path is used when latency tolerance allows it.

This lab does not train those routers. It implements the operational pattern:
price what you can measure, label estimates, and route from request hints plus
KV thresholds.

## Decision

1. **Spend ledger.** Record prompt-safe usage for every completion (sync and
   batch): tokens, cost when an operator price exists, provider, model, channel,
   route mode, and the seven attribution dimensions in
   `cost_attribution_dimensions`. Do not invent prices. Label
   `usage_source` / `measurement_status`.
2. **RoutingPolicy.** Decide sync versus batch from request hints
   (`{"routing": {"latency_tolerant": true}}`) plus KV thresholds. Interactive
   chat stays on the fast path; latency-tolerant or bulk work goes to a batch
   backend.
3. **Batch backend.** Production batch and embeddings traffic targets
   pg-llm-batch. A local in-process backend keeps the standalone path working
   with no external service.

## Consequences

- Cost review is a first-class product surface, not a post-hoc spreadsheet.
- Callers that need interactivity are not forced onto the 24h batch window.
- Learned RouteLLM-style routers remain a future replacement for the
  deterministic policy, and only after evaluation logs show the heuristic is
  the bottleneck.

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language models while reducing cost and improving performance*. arXiv. https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan, L. V. S., & Awadallah, A. H. (2024). Hybrid LLM: Cost-efficient and quality-aware query routing. *The Twelfth International Conference on Learning Representations*. https://doi.org/10.48550/arXiv.2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference data*. arXiv. https://doi.org/10.48550/arXiv.2406.18665
