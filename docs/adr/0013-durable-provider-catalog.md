# ADR 0013: Durable provider catalog and last-known-good composition

- **Status:** Proposed
- **Date:** 2026-08-20
- **Decision owners:** Contextual Orchestrator maintainers

## Context

Registering the five organization provider secrets in PostgreSQL is necessary but
not sufficient. A production process must also retain discovered provider accounts
and models so a transient catalog outage does not erase the serving pool. Operators
must be able to distinguish live discovery from last-known-good metadata. A
GitHub-hosted scheduled runner has an ephemeral filesystem, so SQLite cannot be the
authority for this catalog.

## Decision

Use a third-normal-form PostgreSQL catalog colocated with the encrypted credential
registry. The authority contains four two-or-more-word `snake_case` objects:

- `provider_account`: provider endpoint, discovery contract, and credential
  **name**, never the credential value;
- `provider_model`: account-scoped model identity, known prices, compatibility,
  and lifecycle state;
- `model_serving_tag`: generic serving tags as a separate many-to-many relation;
- `catalog_refresh_run`: provider-local success/failure evidence.

Provider endpoint and authentication attributes depend on `provider_account_id`, so
they are stored only in `provider_account`. `provider_model` joins to that account
when reconstructing runtime candidates; endpoint and auth fields are not duplicated
on each model row.

A successful non-empty provider refresh atomically replaces that provider account's
enabled current set. A failed or empty/malformed refresh records a stable error code
but preserves the account's last-known-good models. Successful discovery of an
authoritative non-chat-only catalog may withdraw earlier chat rows.

Model names are used only for a conservative negative compatibility filter that
excludes obvious embedding, reranking, speech, image, moderation, safety, and
realtime transports. They are never used to infer reasoning, verification, coding,
vision, or provider-native effort capabilities. Those require explicit catalog or
measured evidence under the gateway-owned policy.

## Consequences

- Credentials and model metadata are durable but remain separated.
- NVIDIA primary and secondary keys are independent provider accounts.
- One provider outage does not erase other providers or its own last-known-good set.
- Unknown price remains unknown rather than becoming fabricated zero cost.
- Endpoint changes update one provider-account row instead of every model row.
- The protected hourly workflow can persist catalog metadata without claiming that
  its ephemeral runner activated a durable agent-pool database.
- Long-running deployments may separately synchronize selected catalog rows into a
  persistent agent pool.

## Verification

The merge gate covers normalized DDL, secret-column absence, functional-dependency
separation, provider-account isolation, parameterized PostgreSQL statements,
last-known-good retention, withdrawal after authoritative success, non-chat
filtering, secret-free evidence, and end-to-end recovery when one provider fails.

## References

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

National Institute of Standards and Technology. (2024). *Artificial intelligence
risk management framework: Generative artificial intelligence profile* (NIST AI
600-1). https://doi.org/10.6028/NIST.AI.600-1
