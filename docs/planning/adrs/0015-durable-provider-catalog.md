---
id: "0015"
title: "Durable provider catalog and last-known-good composition"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-22"
deciders:
  - "repository maintainer"
consulted:
  - "NIST SP 800-53 Rev. 5"
  - "NIST AI 600-1"
informed:
  - "LineageWeave"
  - "fast-mlsirm"
  - "contributors"
affected_components:
  - "contextual_orchestrator/provider_bootstrap.py"
  - "contextual_orchestrator/provider_catalog_bootstrap.py"
  - "contextual_orchestrator/provider_catalog_store.py"
  - ".github/workflows/provider-catalog-sync.yml"
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0012-gateway-only-provider-contract.md"
    relation: depends-on
  - path: "docs/planning/adrs/0014-gateway-owned-model-selection.md"
    relation: extends
effort: L
---

# Durable provider catalog and last-known-good composition

## Context

Registering the five organization provider secrets in PostgreSQL is necessary
but not sufficient. A production process must also retain discovered provider
accounts and models so a transient catalog outage does not erase the serving
pool, and operators must distinguish live discovery from last-known-good
metadata. GitHub-hosted scheduled jobs have ephemeral filesystems, so SQLite
cannot be the authority for this catalog.

## Decision

Use a third-normal-form PostgreSQL catalog colocated with the encrypted
credential registry. The authority contains four two-or-more-word
`snake_case` objects:

- `provider_account`: provider endpoint and credential name, never the value;
- `provider_model`: account-scoped model identity, known prices, compatibility
  and lifecycle state; endpoint and authentication fields are joined from its
  owning account;
- `model_serving_tag`: generic serving tags as a separate many-to-many relation;
- `catalog_refresh_run`: provider-local success/failure evidence.

A successful non-empty provider refresh atomically replaces that provider
account's enabled current set. A failed or empty/malformed refresh records only
an allowlisted stable error code and preserves the account's last-known-good
models. Successful discovery of an authoritative non-chat-only catalog may
withdraw earlier chat rows.

Model names are used only for a conservative negative compatibility filter that
excludes obvious embedding, reranking, speech, image, moderation, safety, and
realtime transports. They are never used to infer reasoning, verification,
coding, vision, or provider-native effort capabilities. Those require explicit
catalog or measured evidence under the gateway-owned policy.
Provider-declared `supported_parameters=response_format` is retained as the
`response_format` serving tag and preferred for virtual structured synthesis.
Missing catalog metadata does not itself prove support; configured-gateway rows
must instead pass the runtime probe below. An explicitly requested
operator-managed model remains the operator's transport contract.
Configured-gateway runtime activation additionally performs one bounded,
synthetic `json_object` probe per discovered chat row. Only rows that return a
valid structured object remain chat-serving candidates; a listing alone is not
readiness evidence. Embedding rows retain their separate capability route and
are never subjected to a chat probe.
When live discovery activates a real chat model, only agents explicitly tagged
`bootstrap_seed` are retired. A `mock://` transport alone is not proof that an
agent is disposable; operator-configured mock agents remain in the declared
pool unless the operator disables them.
Catalog presence is also not spend admission. At runtime startup, OpenRouter's
authenticated credits contract supplies `total_credits` and `total_usage`.
Paid OpenRouter models remain individually discoverable but disabled unless
their exact difference is strictly positive; catalog-declared free models stay
eligible. Missing, malformed, or non-finite credit evidence never fabricates
paid capacity. Other providers remain unchanged until they publish an
equivalent machine-readable balance contract.

## Consequences

- Credentials and model metadata are durable but remain separated.
- NVIDIA primary and secondary keys are independent provider accounts.
- One provider outage does not erase other providers or its own last-known-good set.
- Unknown price remains unknown rather than becoming fabricated zero cost.
- A listed paid OpenRouter model cannot enter routing when its provider attests
  zero or negative remaining credit.
- The protected hourly workflow can persist catalog metadata without claiming
  that its ephemeral runner has activated a durable agent-pool database.
- Long-running deployments may separately synchronize selected catalog rows into
  a persistent agent pool.

## Verification

The merge gate covers normalized DDL, secret-column absence, provider-account
isolation, parameterized PostgreSQL statements, last-known-good retention,
withdrawal after authoritative success, non-chat filtering, secret-free
evidence, bounded configured-gateway capability probes, and end-to-end recovery
when one provider fails.

## References

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

National Institute of Standards and Technology. (2024). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

OpenRouter. (n.d.). *Get remaining credits*. Retrieved August 27, 2026, from
https://openrouter.ai/docs/api/api-reference/credits/get-credits
