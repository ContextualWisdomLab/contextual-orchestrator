# Priced selection and default composed catalog

This note is the claim boundary for the unique slice that PR #642 does not
own: default-on model discovery, retention of `original_list_price` when a
model is promotional-free, paper-grounded min-cost / max-performance
selection of **one** worker, and this gateway's own `GET /v1/models`.

## Claims

1. **Default discovery.** When an org credential
   (`NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `BYTEZ_API_KEY`,
   `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) is already present in the KV,
   the gateway `GET`s that provider's `/v1/models` and composes chat
   models into the pool. There is no `--discover-models` opt-in. A static
   fallback row is used **only** when that GET fails or returns no chat
   models (Chen et al., 2023, on pricing unknown upstreams honestly).
2. **Exception isolation.** A timeout, 5xx, or malformed JSON from one
   provider never aborts compose for the others.
3. **Discovery egress (issue #86 / PR #96 boundary).** Catalog `GET` uses
   the same public-HTTPS + globally-routable address pin as chat
   (`provider_base_url_rejection`) and a no-redirect opener. Loopback,
   private, link-local, multicast, and reserved addresses are rejected
   *before* the KV Bearer is attached. A 3xx is refused so the credential
   is never replayed. `allow_insecure` is ignored on the production fetch
   (OWASP Foundation, 2021; Chen et al., 2023).
4. **Cost honesty (issue #86).** Actual free-to-caller (explicit billed
   rates, including `0`) and hypothetical/original list price
   (`original_list_price`) are separate fields. A missing price row, or a
   stub that omits billed rate keys, is `unknown` (`compute_cost` returns
   `None`). Unknown is never converted to `0` or “free.”
   `original_list_price` is never used as billed cost.
5. **Single-worker selection.** Fugu's low-latency path selects one worker
   without an expensive coordinator search (Sakana AI, 2026). Among capable
   workers this lab then applies FrugalGPT / Hybrid LLM ranking: minimize
   **known** billed cost, then maximize the existing capability score (Chen et al.,
   2023; Ding et al., 2024). This is **not** PR #575's capability-first
   then min-known-cost policy. Transient retry stays on the chosen worker.
   Sequential next-agent hopping is not used. A circuit-open worker is
   excluded from the *next* selection (Trinity's compact choose-once
   coordinator; Xu et al., 2025).
6. **Gateway catalog.** `GET /v1/models` lists the facade model
   `contextual-orchestrator` plus the composed pool so first-class `/v1`
   consumers (Noema — review and other jobs — plus gyeot and scopeweave)
   can see candidates. GitHub Models hosts and `COPILOT_GITHUB_TOKEN` are
   rejected.
7. **Out of scope.** PR #642 owns the production seed, flag-gated
   `--discover-models`, OpenCode sidecar, and 429 → next-agent failover.
   PR #575 owns capability-first then min-known-cost ranking. PR #574's
   3NF catalog is not on protected main (`6841b719`) and is not treated
   as landed. This PR does not merge #642.

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*
(arXiv:2305.05176). arXiv. https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). Hybrid LLM: Cost-efficient
and quality-aware query routing. In *Proceedings of the Twelfth
International Conference on Learning Representations*
(arXiv:2404.14618). https://doi.org/10.48550/arXiv.2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* (arXiv:2406.18665). arXiv.
https://doi.org/10.48550/arXiv.2406.18665

OWASP Foundation. (2021). *Server-side request forgery prevention cheat
sheet*. https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y.
(2025). *Learning to orchestrate agents in natural language with the
Conductor* (arXiv:2512.04388). arXiv.
https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y.
(2025). *Trinity: An evolved LLM coordinator* (arXiv:2512.04695). arXiv.
https://doi.org/10.48550/arXiv.2512.04695

OWASP Foundation. (2021). *Server-side request forgery prevention cheat
sheet*. https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

PDFs already vendored under `docs/papers/` (FrugalGPT, RouteLLM, Hybrid
LLM) are redistributed under arXiv's non-exclusive license. Fugu, TRINITY,
and Conductor are cited + linked; attach the PDF only when redistribution
is permissible.
