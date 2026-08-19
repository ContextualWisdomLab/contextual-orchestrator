# Current-main provider bootstrap

## Decision

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

The bootstrap pool is provider-diverse before it is cost-ordered. Missing price is
`unknown`, not zero. This avoids treating a provider such as Bytez, whose public
catalog may use a non-token billing unit, as a fabricated free route.

## Operational workflow

`.github/workflows/provider-catalog-sync.yml` runs hourly on protected `main` and may
also be dispatched manually. It is intentionally absent from pull-request secret
execution. The production environment must provide:

- the five provider secrets above;
- `CONTEXTUAL_ORCHESTRATOR_KV_DSN`; and
- `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`.

The workflow verifies that all five credential names were registered, at least one
model was discovered, a bounded serving candidate set was produced, and no exact
provider secret appears in the emitted report.

## Research and standards grounding

The automatic pool remains a routing input rather than an unsupported claim that a
single cheapest model is universally best. Quality/performance selection remains in
the orchestrator's paper-grounded routing and orchestration layer; this bootstrap
only establishes the candidate set and failure isolation.

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
