# Provider catalog doctoring (APA 7)

This note states what the production agent catalog claims, what it does not
claim, and which papers justify routing, failover, and static-versus-discovered
model lists. Citations follow the *Publication Manual of the American
Psychological Association* (7th ed.).

## Claim boundary

The production seed in `examples/agents.production.json` is a **paper-justified
static catalog** of OpenAI-compatible chat workers. It is not a live snapshot of
every model a vendor sells.

| Claim | Boundary |
| --- | --- |
| NVIDIA NIM primary/secondary | Host is `https://integrate.api.nvidia.com/v1`. Seeded chat models are Llama-3.3-Nemotron-Super-49B-v1.5 and Nemotron-3-Super-120B-A12B, taken from NVIDIA model cards (NVIDIA, 2025, 2026). Additional NIM chat models are appended only when `GET /v1/models` succeeds for `NVIDIA_NIM_API_KEY` or `NVIDIA_NIM_API_KEY_SUB`. |
| OpenAI | Host is `https://api.openai.com/v1`. Static seed uses `gpt-5.5` (already the repo's OpenAI example). Live listing is preferred when `OPENAI_API_KEY` can call `/v1/models`. |
| OpenRouter | Host is `https://openrouter.ai/api/v1`. Static `anthropic/claude-sonnet-4` and `openai/gpt-4.1` are capability tags for coding/review and reasoning until `/v1/models` returns the caller's available set. |
| Bytez | Official OpenAI-compatible base URL is `https://api.bytez.com/models/v2/openai/v1` (Bytez, n.d.). The static chat seed is `Qwen/Qwen3-4B` from that document. A public `/models` list is **not guaranteed**; discovery is best-effort and an empty list keeps this static seed. |
| GitHub Models | **Out of catalog.** `models.github.ai`, Copilot tokens, `gpt-5.6-luna`, and `gpt-5.6-terra` are rejected at agent construction. There is no fallback to GitHub Models when every org secret is missing. |

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
(Li et al., 2025). The production seed only supplies tagged workers those
policies can compose.

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
