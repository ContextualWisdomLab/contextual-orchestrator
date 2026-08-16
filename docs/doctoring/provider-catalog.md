# Provider catalog doctoring (APA 7)

This note states what the production agent catalog claims, what it does not
claim, and which papers justify routing, failover, and static-versus-discovered
model lists. Citations follow the *Publication Manual of the American
Psychological Association* (7th ed.).

## Claim boundary

Live `GET /v1/models` (or the host’s documented OpenAI-compatible list
endpoint) is the **primary catalog**. After each of the five secrets is in the
KV, the gateway lists that host with `get_credential` — never `os.getenv` at
request time. Chat/completion ids are kept; embeddings, rerank, image, audio,
and moderation ids are dropped. A cap keeps coding/review/reasoning-capable
names when a vendor dumps hundreds of ids.

`examples/agents.production.json` (the org static seed) is **only a fallback**
when a provider has no list API, the list call 401/403/404/429/5xxs, or the
body is empty or malformed. A successful list **replaces** that provider’s
seed rows. It is not a live snapshot of every model a vendor sells, and it is
not walked as the serving catalog when discovery succeeds.

| Claim | Boundary |
| --- | --- |
| NVIDIA NIM primary/secondary | Host is `https://integrate.api.nvidia.com/v1`. Live list for `NVIDIA_NIM_API_KEY` / `NVIDIA_NIM_API_KEY_SUB` is the catalog. Seeded Llama-3.3-Nemotron-Super-49B-v1.5 and Nemotron-3-Super-120B-A12B (NVIDIA, 2025, 2026) apply only when that list fails. |
| OpenAI | Host is `https://api.openai.com/v1`. Live `/v1/models` wins. Static `gpt-5.5` is fallback only. |
| OpenRouter | Host is `https://openrouter.ai/api/v1`. Live list wins. Static `anthropic/claude-sonnet-4` and `openai/gpt-4.1` are fallback capability tags. |
| Bytez | Official OpenAI-compatible base URL is `https://api.bytez.com/models/v2/openai/v1` (Bytez, n.d.). A public `/models` list is **not guaranteed**; empty/404 keeps the static `Qwen/Qwen3-4B` seed. |
| Gateway `GET /v1/models` | The orchestrator exposes the composed catalog: `contextual-orchestrator` plus surfaced worker model ids. |
| GitHub Models | **Out of catalog.** `models.github.ai`, Copilot tokens, `gpt-5.6-luna`, `gpt-5.6-terra`, and `github-models/*` ids are rejected. There is no fallback to GitHub Models when every org secret is missing. |

Missing a secret disables that upstream only (`NotConfigured` per agent). The
gateway keeps serving every worker whose credential is present. When no
credential is resolvable, routing fail-closes with `NotConfigured` — it does
not invent a GitHub Models worker.

## Why a multi-upstream catalog (routing papers)

Cost-optimal cascades and quality-aware routers need **more than one capable
upstream**, then a policy that picks a cheap/fast path or a deeper path
(Chen et al., 2023; Ong et al., 2024; Ding et al., 2024). This repo already
implements Fugu-style `route` versus `conduct` (Sakana AI, 2026), TRINITY
thinker/worker/verifier roles (Zhang et al., 2025), and Conductor access lists
(Li et al., 2025). Discovered chat models are tagged coding / review /
reasoning (and cheap / fallback when the id or secondary key says so) so those
policies can compose them. The static seed is not the live walk.

Full-jitter retry on 429/5xx stays inside one worker. If that worker still
fails, the gateway **re-runs the cost-performance chooser** on the remaining
healthy pool (circuit-open agents excluded). That is re-selection, not “the
next name in the seed file” (Chen et al., 2023; Ding et al., 2024). See
[cost_performance_routing.md](cost_performance_routing.md).

## References

Bytez. (n.d.). *Chat completions*. Bytez Model API.
https://docs.bytez.com/http-reference/examples/openai-compliant/chatCompletionsExample

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance*. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan,
L. V. S., & Hassan Awadallah, A. (2024). *Hybrid LLM: Cost-efficient and
quality-aware query routing*. In *Proceedings of the Twelfth International
Conference on Learning Representations*. https://doi.org/10.48550/arXiv.2404.14618

Li, Y., et al. (2025). *Learning to orchestrate agents in natural language with
the Conductor*. arXiv. https://doi.org/10.48550/arXiv.2512.04388

NVIDIA. (2025). *Llama-3.3-Nemotron-Super-49B-v1.5* [Model card].
https://build.nvidia.com/nvidia/llama-3_3-nemotron-super-49b-v1_5

NVIDIA. (2026). *Nemotron-3-Super-120B-A12B* [Model card].
https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data*. arXiv. https://doi.org/10.48550/arXiv.2406.18665

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Zhang, et al. (2025). *TRINITY: An evolved LLM coordinator*. arXiv.
https://doi.org/10.48550/arXiv.2512.04695

Redistributable arXiv PDFs already vendored under `docs/papers/` (FrugalGPT,
RouteLLM, Hybrid LLM) remain the cost/routing evidence pack. Vendor model cards
and the Fugu launch article are cited by URL only; they are not copied here.
