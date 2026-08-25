# ADR 0026: Measured model groups and cost-aware discovery

- Status: Proposed on the active feature head
- Date: 2026-08-25
- Figma file ID: `vsZMd8WAv42HDRgcZuNcWk`; this change reuses the existing Agent Pool table rather than introducing a new visual pattern.
- Product/technical specification: [`docs/model-group-product-technical-spec.md`](../../model-group-product-technical-spec.md)

## Product requirement

Operators need one logical model name when several providers expose the same underlying model under unrelated identifiers. Groups are entirely operator-defined: discovery never infers equivalence from provider or model names, and no model family is built in. Model discovery remains provider-specific and retains the complete catalog; zero-cost entries are additionally classified so cost policy can distinguish free, priced, and unknown-price models.

## Decision and technical contract

`ModelAgent.group_name` is persisted by the existing Agent Pool database, accepted by its create/PATCH APIs, and shown with measured routing evidence in the Admin web table. Static role/capability ranking chooses a logical model group before its members are ordered by observed successful responses per second. An explicit group alias resolves to the currently preferred enabled member. Failover and circuit-breaker behavior remain intact. Discovery never guesses that differently named provider models are equivalent; an operator or future verified canonical-identity feed must assert that relationship.

Capability routing is modality-aware rather than model-name-aware. Discovery preserves provider-declared input and output modalities and exposes `text`, `image`, `video`, `speech`, `transcription`, `embedding`, `rerank`, and `audio` tags; it does not infer a missing modality from a model identifier. The same measured group-member selection and failover path serves text/chat, images, videos, speech, transcription, embeddings, reranking, and audio. OpenRouter is queried with `output_modalities=all`, because its API otherwise defaults to text-only discovery. Provider-declared direction is retained as `input:<modality>` and `output:<modality>` tags so an input-capable vision model is not mistaken for an image generator.

Stability uses the posterior mean of a Bernoulli success probability under a uniform Beta(1, 1) prior. Latency uses Jacobson's exponentially weighted estimator with gain 1/8. The ranking quantity `posterior success probability / EWMA seconds` has the interpretable unit expected successful responses per second and contains no arbitrary cross-metric weight. This quotient is a gateway design decision, not a claim reproduced from the cited routing studies. RouteLLM and FrugalGPT support learned cost/quality routing between distinct models; they motivate the later quality-aware layer but do not validate treating provider aliases as different model quality.

OpenRouter discovery reads its provider-reported per-token prices and recognizes explicit zero prices. OpenCode Zen discovery uses its documented `/zen/v1/models` endpoint; because that response currently omits prices, only identifiers explicitly ending in `-free` or `:free` are classified free. Unknown price is never converted to zero. All discovered models remain available for later policy decisions.

Two durable virtual models replace transient examples: `orchestrator/auto` uses
the full eligible pool, while `orchestrator/free` admits only models carrying
discovery's explicit `cost:free` evidence or an operator-configured exact zero
price. An empty free pool fails closed instead of spending money. Both retain
role/capability ranking and measured group-member routing. On `/v1/responses`,
streamed orchestration progress uses OpenAI's
`response.reasoning_summary_part.*` and
`response.reasoning_summary_text.*` events. These contain fixed stage summaries,
not hidden chain-of-thought or intermediate agent output.

```mermaid
sequenceDiagram
  participant Client
  participant Gateway
  participant Group as operator-defined group
  participant OR as OpenRouter
  participant Zen as OpenCode Zen
  Client->>Gateway: model = logical group name
  Gateway->>Group: rank enabled members
  Group->>OR: best measured member
  OR-->>Group: success/failure + latency
  Group-->>Gateway: response or bounded failover
  Gateway-->>Client: provider-neutral response
```

## Data, web, and operational boundaries

Group membership survives restart in normalized `model_group` and `model_group_member` relations; the agent JSON payload no longer duplicates `group_name`. Startup migrates legacy payload membership transactionally without dropping agent configuration. Authenticated REST resources provide `GET/POST /api/v1/model_groups` and `GET/PATCH/DELETE /api/v1/model_groups/{group_name}`; deleting a group retains its provider agents. The existing worker-agent create/PATCH API also accepts `group_name`. Admin provides a keyboard/native-form editor backed by those same resources and shows capability coverage, posterior success probability, and EWMA latency instead of fabricated capacity/success figures. The observation ledger intentionally resets on process restart: persisting it without a measurement horizon would let stale provider incidents dominate current routing. Add a normalized, time-windowed observation table when multi-instance aggregation and an explicit retention/decay policy are specified.

```mermaid
erDiagram
  agent_pool ||--o| model_group_member : "belongs through"
  model_group ||--o{ model_group_member : contains
  agent_pool {
    text agent_id PK
    text payload
  }
  model_group {
    text group_name PK
  }
  model_group_member {
    text agent_id PK,FK
    text group_name FK
  }
```

## Verification and gaps

- Contract tests cover canonical aliases, static tie behavior, measured reordering, snapshot safety, DB/API group persistence, full-catalog discovery, free classification, and the absence of implicit grouping.
- Capability tests cover all eight requested model surfaces, group-scoped measured selection, binary speech preservation, and OpenRouter modality metadata without paid inference. An opt-in live test may use a currently free model, but the deterministic contract suite never assumes that a transient free model will remain listed.
- Gap: provider-reported OpenCode Zen pricing is unavailable in `/models`; retain `unknown` rather than infer paid prices.
- Gap: response quality is not yet in this intra-model score. Distinct-model composition must use calibrated evaluation evidence (for example fast-mlsirm), not a hand-authored weight.
- Gap: multi-replica telemetry needs a time-windowed durable store and concurrency-safe aggregation before production horizontal scaling.
- Gap: final answer deltas for conducted workflows begin after synthesis; true
  token streaming across dependent workflow steps would require a cancellable
  asynchronous execution graph.

## References

Chen, L., Zaharia, M., & Zou, J. (2024). FrugalGPT: How to use large language models while reducing cost and improving performance. *Transactions on Machine Learning Research*. https://arxiv.org/abs/2305.05176

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM Computer Communication Review, 18*(4), 314–329. https://doi.org/10.1145/52325.52356

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference data* [Preprint]. arXiv. https://arxiv.org/abs/2406.18665

OpenCode. (2026). *Zen*. https://opencode.ai/docs/zen

OpenAI. (2026). *OpenAI OpenAPI specification: Responses streaming events*.
https://github.com/openai/openai-openapi/blob/master/openapi.yaml

OpenRouter. (2026). *List all models and their properties*. https://openrouter.ai/docs/api/api-reference/models/get-models

OpenRouter. (2026). *Create speech*. https://openrouter.ai/docs/api/api-reference/speech/create-audio-speech

OpenRouter. (2026). *Image generation*. https://openrouter.ai/docs/guides/overview/multimodal/image-generation

OpenRouter. (2026). *Create transcription*. https://openrouter.ai/docs/api/api-reference/transcriptions/create-audio-transcriptions

OpenRouter. (2026). *Submit a rerank request*. https://openrouter.ai/docs/api/api-reference/rerank/create-rerank

OpenRouter. (2026). *Submit a video generation request*. https://openrouter.ai/docs/api/api-reference/video-generation/create-videos

Ma, H., Lai, G., & Ye, H.-J. (2026). *MMR-Bench: A comprehensive benchmark for multimodal LLM routing* [Preprint]. arXiv. https://arxiv.org/abs/2601.17814
