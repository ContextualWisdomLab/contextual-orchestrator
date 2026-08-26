# ADR 0003: Cost-aware sync-versus-batch routing

- Status: Accepted
- Date: 2026-08-25
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not planning ADR 0003
  (`docs/planning/adrs/0003-keyverse-authentication-boundary.md`).

## Context

LLM API prices differ by orders of magnitude across providers and models, and
bulk or latency-tolerant work is cheaper on a batch path than on an
interactive path. Three arXiv preprints already vendored in
`docs/papers/README.md` ground that cost-review plus routing hub:

- **FrugalGPT** shows heterogeneous LLM API prices and motivates pricing each
  request, then selecting a cheaper capable combination (Chen et al., 2023).
- **RouteLLM** frames routing as choosing a stronger or weaker model to hit a
  cost/quality target (Ong et al., 2024).
- **Hybrid LLM** routes easier or bulk queries to a cheaper path and keeps
  harder or interactive queries on the responsive path (Ding et al., 2024).

Those papers describe *learned* routers (cascades, preference-trained
routers, quality-gap predictors). This lab's current `RoutingPolicy` is
deterministic and config-driven: request hints plus KV thresholds choose
sync versus batch, and a price table can pick the cheapest capable upstream.
There is no trained router in this repository.

All three sources are arXiv **preprints** (DOIs under `10.48550/arXiv.*`).
They are not treated as final archival versions. `docs/papers/README.md`
notes Hybrid LLM as ICLR 2024; this ADR cites the verified arXiv record
only.

## Decision

1. **Cost review is first-class.** Every completion, sync and batch, writes a
   prompt-safe usage record with token counts, computed cost, and the
   seven attribution dimensions. Raw prompt and answer text are not stored
   on the usage record.
2. **Sync versus batch is a policy, not a model.** `RoutingPolicy` decides
   from caller hints (`routing.latency_tolerant`, `channel`, `priority`) and
   KV thresholds (`batch_enabled`, `batch_min_tokens`,
   `interactive_forces_sync`). Interactive work stays on the sync path;
   latency-tolerant or bulk work may go to a batch backend.
3. **Learned routers are future work.** Do not add a preference-trained or
   cascade router until evaluation logs show the deterministic policy is the
   bottleneck. Cite FrugalGPT, RouteLLM, and Hybrid LLM as design grounding,
   not as a claim that this lab implements those trained systems.
4. **Batch execution is injected.** The production batch backend is an
   optional `pg-llm-batch` client. A local in-process backend keeps the
   standalone path working. Composition details are in
   [ADR 0004](0004-msa-leaf-composition.md).
5. **Remote embedding agents use their provider.** The default coordinator
   may retain deterministic local vectors only when the pool has no configured
   remote embedding agent. Once a remote agent carries the explicit
   `embedding` capability, sync and batch embedding requests call that agent's
   provider endpoint and preserve the resolved model and provider token usage.
6. **Published limits are exact-model contracts.** For OpenAI
   `text-embedding-3-large`, request packing uses the provider-published limits:
   2,048 array inputs, 8,192 tokens per input, and 300,000 tokens per request.
   Token counts use the model's `cl100k_base` tokenizer; character or word-count
   estimates cannot authorize a request. The capability record carries its
   authority URL and is not inherited by another provider or model (OpenAI,
   2026).

## Consequences

### Positive

- Operators can price and route without training data.
- Interactive callers are not forced onto a 24-hour batch window.
- Paper grounding stays honest: the literature motivates the split; the
  implementation remains a config policy.

### Negative

- A learned router would likely beat hint-and-threshold routing on mixed
  quality/cost workloads. That gap is accepted until measured.

### Neutral

- Upstream load-balancing among priced candidates (`cheapest_upstream`) is
  table-driven. It is not RouteLLM's preference model.

## References

OpenAI. (2026). *Create embeddings*. OpenAI API reference.
https://developers.openai.com/api/reference/ruby/resources/embeddings/methods/create

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance* [Preprint].
arXiv. https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Ruhle, V.,
Lakshmanan, L. V. S., & Awadallah, A. (2024). *Hybrid LLM: Cost-efficient
and quality-aware query routing* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2406.18665
