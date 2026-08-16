# Durable Provider Catalog Design

## Decision

`contextual-orchestrator` will treat provider credentials, provider accounts,
model metadata, and orchestration policy as separate control-plane objects.
GitHub Actions secrets are bootstrap transport only. A trusted default-branch
workflow writes the five provider credentials into the existing pgcrypto-backed
credential registry, discovers each account's current model catalog, and stores
normalized model metadata in PostgreSQL. The running gateway reads credential
*names* and model candidates from those durable stores; it does not use provider
API-key environment variables as a runtime source.

The fixed bootstrap inventory is:

| Provider account | Credential name | Discovery/transport |
| --- | --- | --- |
| `nvidia_nim_primary` | `NVIDIA_NIM_API_KEY` | OpenAI-compatible `/v1/models` and chat |
| `nvidia_nim_secondary` | `NVIDIA_NIM_API_KEY_SUB` | Independent NIM account, same contract |
| `bytez_primary` | `BYTEZ_API_KEY` | Native Bytez `Key` and `input` contract |
| `openrouter_primary` | `OPENROUTER_API_KEY` | OpenAI-compatible model catalog and chat |
| `openai_primary` | `OPENAI_API_KEY` | OpenAI model catalog and chat |

NVIDIA's primary and secondary keys remain distinct provider accounts so
quota exhaustion, revocation, health, and circuit state cannot be conflated.

## Product outcome

An operator configures the database connection and the five existing Actions
secrets once. The trusted sync job then maintains a candidate pool without
hand-editing an agents JSON file. At service startup,
`--provider-catalog-dsn` replaces the seed file with enabled database models.
The existing paper-grounded route/conduct engine receives the whole role-tagged
pool and continues to decide between one-model routing and a
Thinker–Worker–Verifier–Synthesizer workflow.

The design does not claim that every listed model is suitable for every task.
Capabilities and modalities constrain routing first; context capacity and
provider/account preference follow; known price is only a small tie-break. The
current deterministic policy remains auditable and replaceable by a learned
router only after evaluation evidence shows that it is the bottleneck.

## Boundaries

### Credential plane

The existing `provider_credentials` table remains the only provider-secret
store. It contains `credential_name` and pgcrypto-encrypted values. The catalog
stores only `credential_name` references. Secret values never appear in model
rows, generated agent JSON, audit summaries, workflow artifacts, or error text.

`bootstrap_provider_credentials()` validates the complete fixed inventory before
writing when `--require-all` is selected. This prevents a production run from
rotating only a subset and leaving an ambiguous mixed generation.

### Catalog plane

The catalog is third-normal-form data:

- `provider_accounts`: account identity, provider, credential name, endpoint,
  transport, enablement, and priority;
- `provider_models`: account-specific model identity, display metadata, context,
  known prices, enablement, and first/last observation;
- `model_capabilities`: one capability per model row;
- `model_modalities`: one modality per model row;
- `catalog_refresh_runs`: immutable per-account refresh outcome evidence.

A successful account refresh atomically upserts the observed set and disables
models absent from that complete response. A failed refresh writes only a
failure record; it never disables or deletes the prior usable set.

### Discovery plane

Credentialed catalog HTTP uses HTTPS, direct DNS-resolved public addresses,
normal certificate/SNI verification, no redirect following, no ambient proxy,
a bounded response, strict JSON object validation, bounded attempts, jittered
backoff, and a wall-clock deadline. Authentication and schema errors fail fast.
Transient network, rate-limit, and 5xx errors are isolated to that account.

The model normalizer accepts the common `data` and `models` shapes, rejects
invalid/oversized identifiers and non-finite metadata, and infers conservative
capabilities from provider metadata plus model naming. Unknown values remain
unknown; the gateway does not fabricate context windows or prices.

### Inference plane

OpenAI, OpenRouter, and NVIDIA NIM continue through the hardened
OpenAI-compatible `ModelClient`. Bytez uses `ProviderAwareModelClient` and its
native `Authorization: Key …` plus `{"input": …}` request shape. Unsupported
Bytez passthrough endpoints fail closed instead of pretending that a native
response is an OpenAI Responses or tool-call object.

Generated `ModelAgent` rows contain model ids, endpoints, provider names,
capabilities, priorities, and credential names only. `TaskOrchestrator` retains
its existing per-agent retry, failover, and circuit-breaker behavior. A provider
catalog with zero enabled candidates is a startup error, not a reason to start a
mock agent.

## Trusted GitHub Actions flow

`.github/workflows/provider-catalog-sync.yml` has two trust-separated jobs:

1. Pull requests run only deterministic offline contracts and compile checks;
   provider secrets are not exposed to contributor code.
2. Scheduled/manual runs execute only on protected `main` in the `production`
   environment. They require the five provider keys plus
   `CONTEXTUAL_ORCHESTRATOR_KV_DSN` and
   `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`, seed the encrypted registry, refresh
   metadata, and verify that generated agent evidence contains no secret value.

Missing database bootstrap secrets block the job. The workflow never downgrades
to process memory, because an ephemeral registry would create a false success
and disappear before the service could use it.

## Failure semantics

| Condition | Result | Operator action |
| --- | --- | --- |
| One provider catalog is unavailable and has prior models | Serve prior models as `stale_available`; refresh peers | Inspect provider health; retry next schedule |
| One provider is unavailable with no prior models | Mark account `failed`; continue peers | Correct endpoint/key or wait for provider |
| All providers fail and no prior model exists | Fail sync/startup | Restore DB/provider connectivity before service |
| Credential missing | Account failure; production `--require-all` blocks before writes | Add/repair the named Actions secret |
| 401/403 | Permanent account failure, no retry storm | Rotate/re-authorize that credential |
| 408/429/5xx/network timeout | Bounded jittered retry, then stale/failure classification | Observe rate and provider SLO |
| Invalid/oversized/non-JSON response | Fail closed without body disclosure | Treat as provider contract/security incident |
| Database failure | Fail closed; no memory fallback | Restore the authoritative catalog/KV database |
| Bytez unsupported response/passthrough | Fail closed, allow normal orchestrator failover where available | Use a supported native chat model or another provider |

## Test and acceptance evidence

The feature is accepted only when all of the following hold on one exact PR
head:

- all five fixed credential names are represented and NVIDIA accounts remain
  independent;
- required bootstrap is all-or-nothing and summaries contain no value;
- normalization, malformed metadata, specialized capabilities, and price/context
  bounds are deterministic;
- provider failures are isolated and last-known-good models survive;
- no-candidate startup fails closed;
- discovered models become valid two-or-more-word snake-case agents;
- role selection and cross-provider failover use the complete candidate pool;
- native Bytez authentication/response handling is tested independently;
- PostgreSQL DDL is normalized and contains no secret-value column;
- the full repository test, 100% branch coverage, 100% public docstring,
  security, fuzz, and protected review gates pass without weakening them; and
- the protected default-branch sync subsequently records real provider and DB
  evidence without revealing credentials.

## Research and standards basis

The route/conduct split follows the repository's existing Fugu, TRINITY, and
Conductor interpretation: cheap single-model selection for suitable work, deeper
role-separated computation when decomposition and verification add value. The
catalog makes the swappable model pool operational rather than static. Cost is
kept subordinate to capability, consistent with cost-aware routing literature
that optimizes under quality constraints rather than choosing the cheapest model
unconditionally.

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
