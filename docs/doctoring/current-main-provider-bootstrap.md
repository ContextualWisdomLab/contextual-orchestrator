# Current-main provider bootstrap

## Decision

The durable catalog decision is recorded in
[`ADR 0015`](../planning/adrs/0015-durable-provider-catalog.md), including the
third-normal-form dependency boundary and the last-known-good refresh contract.

Contextual Orchestrator treats the five organization provider credentials as one
trusted bootstrap inventory:

- `NVIDIA_NIM_API_KEY`
- `NVIDIA_NIM_API_KEY_SUB`
- `BYTEZ_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`

GitHub Actions secrets are transport into a one-shot bootstrap process, not the
runtime credential source. Production bootstrap requires the PostgreSQL credential
backend so values are stored encrypted at rest through the existing pgcrypto
registry. Runtime model discovery resolves credential names through
`get_credential()` only.

## Failure contract

Production bootstrap fails closed when any fixed credential is missing, when the
configured credential backend is not atomic, or when no usable provider model can
be discovered. A provider-local discovery exception does not erase models returned
by other providers; the report contains only stable provider names and counts, never
raw exception strings or credential values.

`registered_credentials` is the post-rollback durable inventory, not merely the
set of candidate names received from Actions. If a first-ever candidate key is
reverted after a failed provider refresh, that name is omitted from the report
and the hourly workflow fails its complete-inventory gate. Existing keys that
are restored remain listed, so a transient provider outage can preserve
last-known-good serving without falsely claiming that a missing key is durable.

A successful generic `/models` response is not itself evidence that every row can
serve Chat Completions. OpenAI-compatible registries may mix chat models with
embeddings, rerankers, speech, image generation, moderation, safety, or realtime
transports. The bootstrap therefore applies a conservative negative compatibility
filter before selection and reports both:

- `discovered_model_count`: every syntactically valid catalog row; and
- `eligible_model_count`: rows that are not clearly a non-chat transport.

If no compatible row remains, bootstrap fails closed instead of activating the
cheapest incompatible model. Surviving rows receive only generic serving tags:
`discovered`, `chat`, `worker`, `writing`, and `synthesizer`. The bootstrap never
infers reasoning, verification, coding, vision, or provider-native effort support
from a model name. Those capabilities require explicit provider/catalog evidence or
measured evaluation and are negotiated by the ordinary runtime policy.

The bootstrap pool is provider-diverse before it is cost-ordered. Missing price is
`unknown`, not zero. This avoids treating a provider such as Bytez, whose public
catalog may use a non-token billing unit, as a fabricated free route.

Candidate selection and durable serving activation are separate claims:

- `selected_agent_ids` records the bounded chat candidates produced by discovery
  and selection;
- `enabled_agent_ids` is populated only when an explicit durable `--agents-db`
  is supplied and the selected agents are confirmed active in that pool; and
- `durable_agent_pool` states whether the activation claim is backed by a
  persistent agent-pool database.

When a durable pool is refreshed, the bootstrap tombstones its synthetic seed and
previously discovered agents that are absent from the current bounded selection.
Operator-managed agents are preserved. This prevents retired, withdrawn, or newly
classified non-chat provider models from continuing to receive traffic after a
later discovery run.

## Operational workflow

`.github/workflows/provider-catalog-sync.yml` runs hourly on protected `main` and may
also be dispatched manually. It is intentionally absent from pull-request secret
execution. Every sync requires the six provider secrets above, including
`OPENCODE_ZEN_API_KEY`. Cross-run
production persistence additionally requires:

- `CONTEXTUAL_ORCHESTRATOR_KV_DSN`; and
- `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`.

The workflow uses the production PostgreSQL KV when both KV secrets are configured.
When neither is configured, it uses a PostgreSQL service scoped to that workflow run
so live provider discovery and the complete security contract remain continuously
verified without claiming cross-run persistence. Configuring only one KV secret
fails closed. Neither storage mode claims durable agent-pool activation. A
long-running service may either use the ordinary KV-backed startup discovery path or
invoke this bootstrap with a persistent `--agents-db` under its own deployment
boundary.

The workflow verifies that all six credential names were registered, at least one
model was discovered, at least one chat-compatible model survived classification, a
bounded serving candidate set was produced, and no exact provider secret appears in
the emitted report.

## Research and standards grounding

The automatic pool remains a routing input rather than an unsupported claim that a
single cheapest model is universally best. Quality/performance selection remains in
the orchestrator's paper-grounded routing and orchestration layer; this bootstrap
only establishes a compatible candidate set and failure isolation.

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

National Institute of Standards and Technology. (2024). *Artificial intelligence
risk management framework: Generative artificial intelligence profile* (NIST AI
600-1). https://doi.org/10.6028/NIST.AI.600-1

Tang, Y., et al. (2026). *Sakana Fugu technical report*. Sakana AI.

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
https://doi.org/10.48550/arXiv.2512.04695

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388). https://doi.org/10.48550/arXiv.2512.04388
