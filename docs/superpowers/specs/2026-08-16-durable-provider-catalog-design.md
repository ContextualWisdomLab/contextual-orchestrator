# Durable Provider Catalog Design

## Decision

`contextual-orchestrator` separates provider credentials, provider accounts,
model metadata, and orchestration policy into distinct control-plane objects.
GitHub Actions secrets are bootstrap transport only. A trusted protected-main
workflow writes the five provider values into the existing pgcrypto credential
registry, discovers each account's current model inventory, and persists
normalized metadata in PostgreSQL. The running gateway resolves credential names
from the registry and enabled chat candidates from the catalog; it never treats
provider-key environment variables as a runtime secret source.

The fixed account inventory is:

| Provider account | Credential name | Catalog and inference contract |
| --- | --- | --- |
| `nvidia_nim_primary` | `NVIDIA_NIM_API_KEY` | OpenAI-compatible |
| `nvidia_nim_secondary` | `NVIDIA_NIM_API_KEY_SUB` | Independent OpenAI-compatible NIM account |
| `bytez_primary` | `BYTEZ_API_KEY` | Native Bytez `Key` and `input` contract |
| `openrouter_primary` | `OPENROUTER_API_KEY` | OpenAI-compatible |
| `openai_primary` | `OPENAI_API_KEY` | OpenAI-compatible |

NVIDIA primary and secondary remain distinct so quota exhaustion, revocation,
refresh health, and runtime circuit state are never conflated.

## Product outcome

After one protected synchronization, operators start the service with
`--provider-catalog-dsn`. The bundled seed file is replaced by enabled database
candidates. The existing paper-grounded route/conduct engine receives the whole
eligible model pool and continues to decide between one-model routing and a
Thinker–Worker–Verifier–Synthesizer workflow with access lists, retries,
failover, and circuit breaking.

The database may retain embedding, reranking, image, speech, moderation, video,
and unknown models for inventory purposes, but only candidates carrying a
validated or conservatively inferred `chat`, `reasoning`, or `coding`
capability enter the chat orchestration pool. This prevents an arbitrary model
listing from being treated as a chat worker.

Capability and role fit govern selection first. Provider/account preference,
context capacity, and known price are bounded ties. Missing prices remain null;
price never substitutes for quality or capability.

## Components

### Credential plane

The existing `provider_credentials` table remains the sole provider-secret
store. Catalog rows contain only `credential_name`. Required bootstrap validates
the complete five-key generation before any write so a production rotation
cannot leave a mixed partial generation.

### Catalog plane

The third-normal-form catalog comprises:

- `provider_accounts`: account identity, provider, credential name, endpoint,
  transport, enablement, and account priority;
- `provider_models`: account-specific model identity, display metadata, context,
  known prices, enablement, and observation timestamps;
- `model_capabilities`: one capability per model;
- `model_modalities`: one modality per model;
- `catalog_refresh_runs`: immutable account-scoped outcome evidence.

A complete successful account refresh atomically upserts the observed set and
disables models absent from that response. A failed, empty, malformed, or
unauthorized refresh writes failure evidence only and leaves its prior model set
unchanged.

### Discovery plane

Catalog HTTP is HTTPS-only and credentialed. It resolves and validates public
addresses, dials only the approved addresses, preserves the provider hostname for
TLS/SNI, bypasses ambient proxies, rejects redirects, bounds response bytes,
requires JSON media, and applies the repository strict JSON-object parser. It
rejects duplicate members, malformed UTF-8, non-finite values, and non-object
roots before normalization.

Transient network, timeout, rate-limit, and 5xx errors use bounded attempts,
full-jitter exponential backoff, a wall-clock deadline, and a maximum 30-second
`Retry-After` authority. Authentication, unsafe destination, malformed contract,
and empty catalog errors fail fast. Each provider account refresh is isolated.

### Capability normalization

Provider-declared capabilities are authoritative when present. Otherwise the
normalizer uses conservative model-family evidence:

- embedding, reranking, moderation/guard, transcription, speech generation,
  image generation, and video generation are specialized non-chat categories;
- common LLM/instruct/chat families can become `chat` candidates;
- reasoning, coding, vision, and audio enrich only chat-capable candidates;
- unrecognized models are `unknown`, remain inventoried, and are not served.

Context, modality, and price metadata are bounded and finite. Unknown evidence is
stored as null, never fabricated as zero.

### Inference plane

OpenAI, OpenRouter, and NVIDIA NIM use the hardened OpenAI-compatible
`ModelClient` inherited from the provider-security prerequisite. Bytez uses a
narrow native adapter: text-only role/content messages are serialized to a
bounded prompt, authentication uses `Authorization: Key`, and the request uses
`input`. Unsupported Bytez Responses/tool passthrough or ambiguous output shapes
fail closed rather than being rewritten into invented OpenAI objects.

Generated `ModelAgent` rows contain only ids, model ids, endpoints, providers,
role tags, priorities, and credential names. An empty eligible catalog is a
startup error; catalog mode never falls back to bundled mock agents.

## GitHub Actions trust boundary

`.github/workflows/provider-catalog-sync.yml` has two jobs:

1. Pull requests run secret-free deterministic contracts and compile checks.
2. Scheduled/manual execution runs only on protected `main` in the `production`
   environment, requires all five provider keys plus
   `CONTEXTUAL_ORCHESTRATOR_KV_DSN` and
   `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`, seeds encrypted credentials,
   refreshes metadata, exports a secret-free agent snapshot, and rejects any
   generated evidence containing an exact secret value.

Missing durable database bootstrap configuration blocks the job. An ephemeral
memory registry would disappear before runtime and therefore cannot be reported
as success.

## Failure semantics

| Condition | Result |
| --- | --- |
| One account fails and has prior models | `stale_available`; peers refresh and service continues |
| One account fails without prior models | Account `failed`; peers continue |
| All eligible accounts fail with no prior chat model | Sync/startup fails closed |
| Required key is missing | Complete bootstrap rejected before any credential write |
| 401/403 | Permanent account failure; no retry storm |
| 408/409/425/429/5xx/network timeout | Bounded retry, then stale/failed classification |
| Unsafe address, redirect, invalid JSON/media, oversized response | Fail closed without provider body disclosure |
| PostgreSQL unavailable | Fail closed; no process-memory downgrade |
| Non-chat model inventory only | Persist inventory but refuse chat-gateway startup |
| Bytez unsupported message/output/passthrough | Fail closed; ordinary orchestrator may choose another eligible provider |

## Acceptance

One exact PR head must demonstrate:

- all five credential names and independent NIM accounts;
- all-or-nothing required bootstrap and value-free summaries;
- normalized 3NF data with no secret-value catalog column;
- strict bounded discovery, Retry-After handling, and stable redacted errors;
- conservative capability classification and non-chat exclusion;
- provider-local failure isolation and last-known-good preservation;
- no-candidate startup failure;
- valid model-agent naming, role selection, and cross-provider failover;
- native Bytez success and fail-closed ambiguity;
- catalog-backed prompt, evaluation, and serve CLI paths;
- repository 100% branch coverage and 100% public-docstring coverage;
- unchanged security, fuzz, review, and protected-merge gates; and
- a later protected-main live synchronization before any claim that production
  provider values or models were actually registered.

## Research and standards basis

The route/conduct split follows the repository interpretation of Fugu, TRINITY,
and Conductor: use a suitable single model when appropriate, and spend deeper
role-separated test-time computation when decomposition and verification add
value. FrugalGPT and RouteLLM motivate quality-constrained cost-aware routing;
they do not justify cheapest-model selection without task fit. RFC 9110 informs
safe bounded retry and `Retry-After`; NIST AI RMF supports traceable inventory,
monitoring, and incident treatment; PostgreSQL pgcrypto provides the existing
encryption-at-rest boundary.

### References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance*. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110).
Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

*Learning to orchestrate agents in natural language with the Conductor*.
(2025). arXiv. https://arxiv.org/abs/2512.04388

National Institute of Standards and Technology. (2023). *Artificial intelligence
risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data*. arXiv. https://doi.org/10.48550/arXiv.2406.18665

PostgreSQL Global Development Group. (2026). *pgcrypto*.
https://www.postgresql.org/docs/current/pgcrypto.html

Sakana AI. (2026). *Fugu technical report*.
https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf

*TRINITY: An evolved LLM coordinator*. (2025). arXiv.
https://arxiv.org/abs/2512.04695
