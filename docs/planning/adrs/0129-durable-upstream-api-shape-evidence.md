---
id: "0129"
title: "Durable upstream API-shape evidence"
status: proposed
proposed_date: "2026-09-04"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/model_discovery.py"
  - "contextual_orchestrator/provider_catalog_store.py"
  - "contextual_orchestrator/orchestrator.py"
related:
  - path: "docs/planning/adrs/0128-openai-chat-responses-shape-translation.md"
    relation: depends-on
---

# Durable upstream API-shape evidence

## Context

ADR 0128 translates requests only after a `ModelAgent` carries the exclusive
`api:chat_completions_only` or `api:responses_only` tag. The current discovery
record has no API-shape observation, the durable provider catalog has no table
for probe evidence, and agent materialization cannot distinguish a declared tag
from a transient or guessed result. Adding live probes directly to ADR 0128
would therefore create an unowned, non-durable inference that could reroute
production traffic after a timeout, quota error, or regional outage.

The static API-version registry is intentionally empty. Every production source
currently configured by `PROVIDER_MODEL_SOURCES` uses an OpenAI-compatible API
that does not require an explicit version. Azure's current `/openai/v1` contract
uses implicit versioning. Native Anthropic requires `anthropic-version`, but its
Messages wire format is neither Chat Completions nor Responses, so registering
it before a native-shape adapter exists would falsely claim a usable provider.

## Decision

Implement shape discovery as a provider-catalog capability in a follow-up code
slice, not inside the translation PR:

1. Run one bounded, non-retrying minimal request against both
   `chat/completions` and `responses` for the exact provider account and model.
2. Record each observation durably with provider account ID, provider model ID,
   endpoint shape, observed time, sanitized outcome class, source URL identity,
   and catalog refresh ID. Never persist response bodies or credentials.
3. Treat success as positive support. Treat authentication, quota, timeout,
   transport, and unknown server errors as inconclusive. Treat an endpoint as
   unsupported only from a provider-documented capability or a stable,
   explicitly classified unsupported-endpoint response.
4. Materialize an exclusive `api:*_only` tag only when one shape has positive
   evidence and the other has definitive unsupported evidence from the same
   provider account, model, and current refresh. Conflicting or stale evidence
   produces no exclusive tag and fails closed at translation admission.
5. Carry the evidence identity into agent-pool persistence so restart and admin
   edits cannot detach a tag from its source observation.

API-version metadata follows the same ownership rule. A version declaration is
added only with a production provider source whose authentication and wire
shape are supported end to end. The provider source owns the declaration; the
transport consumes it without provider-name conditionals. Native Anthropic
onboarding therefore first requires an OpenAI-to-Messages adapter. Legacy Azure
dated versions are not introduced because the current v1 API does not require
them.

## Acceptance criteria

- PostgreSQL and in-memory catalog tests prove observation persistence,
  replacement by refresh, and stale-evidence rejection.
- Endpoint tests prove success/unsupported yields one exclusive tag, while
  timeout, 401/403, 429, 5xx, and conflicting results yield none.
- Agent-pool round trips preserve evidence identity with the derived tag.
- No probe retries, credentials, provider bodies, or raw error text enter the
  durable record.
- ADR 0128 remains the translation dependency and is not merged through this
  proposed prerequisite PR.

## Consequences

This PR records the prerequisite and ownership boundary only; it does not claim
active detection is implemented. The implementation needs a schema migration,
catalog refresh integration, and endpoint-level tests in one bounded follow-up
before the tags can be generated automatically.

## References

Microsoft. (n.d.). *Azure OpenAI in Microsoft Foundry Models v1 API*.
Microsoft Learn.
https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle

OpenAI. (n.d.). *Chat Completions API reference*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/chat

OpenAI. (n.d.). *Responses API reference*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/responses
