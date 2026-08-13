# OpenAI sampling passthrough and attribution honesty

## Purpose

Document the commercial API contract for OpenAI-compatible **Completions** and
**chat Completions** sampling parameters and cost-ledger attribution dimensions
shipped on the main-base PR band (#298–#308). Buyers must be able to trust that
accepted request fields either affect generation or fail closed.

## Behaviour summary

### Applied (request-scoped)

The gateway applies the following knobs to `ModelClient` for the duration of a
single request and restores prior defaults afterward:

| Field | Path | Effect |
|---|---|---|
| `temperature` | Completions + chat | Sampling temperature on provider payload |
| `top_p` | Completions + chat | Nucleus sampling when set |
| `max_tokens` | Completions + chat | Caps `ModelClient.max_output_tokens` |
| `presence_penalty` | Completions + chat | Provider `presence_penalty` when set |
| `frequency_penalty` | Completions + chat | Provider `frequency_penalty` when set |

### Attribution (cost ledger)

| Source | Dimension | Rule |
|---|---|---|
| OpenAI `user` | `account` | Fills when `attribution.account` unset |
| Request `model` | `model_name` | Fills when `attribution.model_name` unset; explicit wins on rollup |
| Endpoint surface | `service` | `completions_api` or `chat_completions_api` when unset |

### Fail-closed (not implemented on route path)

Fields that OpenAI SDKs may send but this gateway does not apply on the
orchestrated route path are **rejected** after type/shape validation rather than
silently ignored (examples: `seed`, `logit_bias`, `stop` on chat; Completions
honesty band for `echo=true`, `best_of>1`, non-empty `suffix`, integer `logprobs`).

## Research and standards grounding (APA 7th)

OpenAI documents temperature, top_p, max_tokens, penalties, stop, seed, and
logit_bias as first-class Completions/chat parameters (OpenAI, 2024). Cost-aware
multi-provider routing and accounting remain grounded in FrugalGPT cascade
pricing (Chen et al., 2023), preference-based routing (Ong et al., 2024), and
hybrid quality/cost query routing (Ding et al., 2024). Fail-closed handling of
unsupported flags is a commercial honesty choice aligned with fail-safe API
gateway practice rather than a claim that those features are implemented.

### References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* (arXiv:2305.05176).
https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan,
L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM: Cost-efficient and
quality-aware query routing* (arXiv:2404.14618).
https://doi.org/10.48550/arXiv.2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data* (arXiv:2406.18665). https://doi.org/10.48550/arXiv.2406.18665

OpenAI. (2024). *API reference: Chat and Completions*.
https://platform.openai.com/docs/api-reference

Vendored PDF mirrors for the arXiv items above live under `docs/papers/` (see
`docs/papers/README.md`).
