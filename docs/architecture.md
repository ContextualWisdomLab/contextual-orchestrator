# Architecture Notes

## Sources Read

- Sakana AI launch article, "Sakana Fugu: One Model to Command Them All" (June 22, 2026): https://sakana.ai/fugu-release/
- Sakana Fugu Technical Report: https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- TRINITY: An Evolved LLM Coordinator: https://arxiv.org/abs/2512.04695
- Learning to Orchestrate Agents in Natural Language with the Conductor: https://arxiv.org/abs/2512.04388
- FrugalGPT: https://arxiv.org/abs/2305.05176
- RouteLLM: https://arxiv.org/abs/2406.18665
- HTTP Semantics (RFC 9110): https://www.rfc-editor.org/rfc/rfc9110
- NIST AI Risk Management Framework 1.0: https://doi.org/10.6028/NIST.AI.100-1
- PostgreSQL pgcrypto: https://www.postgresql.org/docs/current/pgcrypto.html

## What The Architecture Is

The public shape is a single model API. The internal shape is a durable provider
catalog plus a model pool and coordinator that decide when to answer directly,
when to delegate, how much context each worker receives, when to verify, and how
to synthesize the final answer.

The useful split is quality-latency, not separate products:

- Low-latency routing: select one eligible worker for the current query or turn.
- Deep orchestration: create a multi-step workflow when the task needs
  decomposition, independent attempts, verification, or synthesis.

TRINITY contributes the compact coordinator idea: a small model representation
plus a lightweight head can choose agent and role over multiple turns. Its
Thinker, Worker, and Verifier contracts are practical enough to implement
directly.

Conductor contributes the workflow representation: each step is a
natural-language subtask, an assigned worker, and an access list of prior step
outputs. This prevents every worker from being dragged into the same transcript
while still allowing deliberate collaboration.

The Fugu report combines these ideas into production constraints:

- Fugu is optimized for latency by selecting a worker without expensive
  coordinator generation.
- Fugu-Ultra is optimized for quality by generating deeper workflows over a
  broader agent pool.
- The agent pool is swappable, allowing provider preference, model exclusion,
  and compliance controls.
- Multi-agent tool/function-call workflows need memory discipline: isolate
  agents inside the current workflow, but keep useful shared memory across turns.

FrugalGPT and RouteLLM contribute the quality-constrained cost frontier: model
cost matters only after task suitability and expected quality. This repository
therefore keeps capability/role scoring ahead of context and known-price ties.

## Durable Provider Control Plane

The static seed file remains the standalone development path. Production can use
`--provider-catalog-dsn` to load an automatically synchronized pool from
PostgreSQL.

The control plane has two distinct stores:

1. The pgcrypto credential registry stores provider API-key values encrypted at
   rest under stable credential names.
2. The provider catalog stores only account identity, credential name,
   endpoints, models, capabilities, modalities, known prices, enablement, and
   refresh evidence.

The fixed provider accounts are NVIDIA NIM primary, NVIDIA NIM secondary, Bytez,
OpenRouter, and OpenAI. The two NIM credentials remain independent so quota,
revocation, refresh health, and runtime circuit state cannot be conflated.

Catalog refreshes are account-scoped. A complete success atomically replaces
that account's current observed set. A failure records a stable code and retains
last-known-good rows. A provider outage therefore cannot erase peer providers or
its own prior model inventory.

Not every inventoried model is a chat worker. Provider-declared capability
metadata is preferred; otherwise conservative family evidence distinguishes
chat/reasoning/coding from embeddings, reranking, moderation, transcription,
speech generation, image generation, video generation, and unknown models. Only
chat/reasoning/coding candidates become `ModelAgent` rows.

GitHub Actions secrets are bootstrap transport only. Pull requests receive none.
A protected-main production job validates the complete five-key generation plus
the durable DSN/passphrase, writes the encrypted registry, refreshes metadata,
and rejects generated evidence containing an exact secret value.

## Implementation Mapping

- `contextual_orchestrator.orchestrator.ModelAgent`: one configured worker model.
- `TaskOrchestrator.complete()`: route-versus-conduct decision.
- `WorkflowStep.access`: Conductor-style visibility control.
- `ModelClient`: hardened OpenAI-compatible HTTP client.
- `contextual_orchestrator.provider_catalog.ProviderCatalogService`: isolated
  provider synchronization and eligible candidate construction.
- `PostgresProviderCatalogStore`: normalized durable metadata and immutable
  refresh evidence.
- `ProviderCatalogHttpClient`: bounded HTTPS model discovery with strict JSON,
  public-address pinning, deadlines, jitter, and capped `Retry-After`.
- `ProviderAwareModelClient`: existing OpenAI-compatible path plus a narrow
  native Bytez Key/input seam.
- `contextual_orchestrator.server`: OpenAI-compatible HTTP delivery.

The deliberate simplification remains the coordinator policy. The paper systems
learn routing and topology from rewards; this lab uses deterministic role/domain
scoring so the repository runs without training data, GPUs, or vendor
credentials. Add learned routing only when an evaluation set and logs prove the
heuristic policy is the bottleneck.

## Failure and Safety Boundaries

- Catalog mode is authoritative: unavailable database or zero eligible
  candidates blocks startup and never selects bundled mocks.
- Provider model discovery is HTTPS-only, direct, public-address validated,
  hostname-verified, redirect-free, response-bounded, and strict-JSON parsed.
- Transient failures retry within bounded attempts/deadline; 401/403 and
  malformed contracts fail fast.
- `Retry-After` delta/date authority is capped at 30 seconds.
- Failed refreshes preserve last-known-good models.
- Provider values never enter catalog rows, agent JSON, traces, summaries, or
  exception text.
- Native Bytez ambiguity and unsupported OpenAI passthrough fail closed; no
  response-shape guessing is permitted.
- Existing per-agent failover and circuit breakers continue to isolate runtime
  provider failures.

## Product Planning Interpretation

The product is not a Fugu clone. It is a provider-neutral control plane for the
same public shape: one compatible API with hidden routing and orchestration. The
enterprise value comes from exposing operating evidence:

- durable account/model inventory and provider exclusion;
- refresh status and last-known-good continuity;
- latency-quality policy for route versus conduct;
- thinker, worker, verifier, and synthesizer role traces;
- natural-language subtasks and access lists;
- replayable evaluation before learned coordination; and
- credential-name authority without secret disclosure.

See [product_planning.md](product_planning.md),
[provider_catalog.md](provider_catalog.md), and
[doctoring/durable-provider-catalog.md](doctoring/durable-provider-catalog.md).
