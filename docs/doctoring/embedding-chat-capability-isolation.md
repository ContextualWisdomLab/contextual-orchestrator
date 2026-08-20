# Embedding-to-chat capability isolation incident

**Status:** Accepted incident decision
**Date:** 2026-08-20
**Affected consumer:** LineageWeave buyer-surface stack around PR #260

## Incident

A conducted workflow reached the final contextual-orchestrator synthesizer with
`model_group=text-embedding-3-large` and deployment
`azure/text-embedding-3-large`. The gateway rejected the chat operation as
unsupported. Its configured fallback map contained chat-generation model groups,
but no fallback attached to the embedding group.

The missing fallback was a symptom, not the causal defect. An embedding deployment
had already crossed the chat-agent capability boundary and become eligible for a
worker role.

## Causal boundary

Provider-compatible `/models` registries can contain multiple endpoint families.
The original discovery parser accepted every non-empty model identifier and exposed
it to agent creation, price selection, and durable pool synchronization. A catalog
row naming an embedding deployment could therefore be scored for thinker, worker,
verifier, or synthesizer work even though its serving endpoint accepts embedding
input rather than chat messages.

The first incident fix closed discovery and price-routing boundaries, but further
root-cause tracing showed an already-persisted incompatible `ModelAgent` could still
survive that filter. The runtime ranking path, generated workflow assignment,
cross-agent failover, readiness probe, streaming path, and direct
`ModelClient.chat()` path previously trusted the persisted model identifier. That
stale-state path is sufficient to reproduce the same unsupported Azure chat
operation after a process restart or durable bootstrap.

OpenAI documents `text-embedding-3-large` under the embeddings endpoint, separately
from models supported by chat completions. Microsoft likewise demonstrates it with
`client.embeddings.create`, not `client.chat.completions.create`. LiteLLM exposes
chat, responses, embeddings, image, audio, rerank, and other endpoint families as
distinct operations. A router fallback can choose another deployment for the same
operation; it cannot make an embedding deployment execute a chat operation.

## Decision

Chat transport compatibility and general agent-role eligibility are separate
shared runtime invariants. A provider may expose an audio-capable model or a
policy classifier through Chat Completions while that model remains unsuitable
for ordinary thinker, worker, verifier, or synthesizer work.

1. Normalize provider prefixes and common separators in model identifiers.
2. At the transport boundary, reject identifiers that clearly advertise embedding,
   reranking, transcription, moderation-endpoint, image-generation, realtime, or
   speech-only semantics.
3. Keep provider-documented audio and policy-classifier models transport-compatible
   when they are served through Chat Completions.
4. At discovery and ordinary orchestration-role boundaries, additionally exclude
   explicit guard, safety, and NemoGuard policy classifiers.
5. Apply the general-role guard while parsing both OpenAI-compatible and Bytez
   catalogs and before converting, pricing, or cost-selecting a discovery record.
6. Remove stale ineligible agents from thinker, worker, verifier, and synthesizer
   ranking even if a durable configuration still contains them.
7. Reselect a generated workflow step that explicitly names a stale ineligible
   agent and omit such agents from planner inventory.
8. Remove ineligible agents from cross-agent failover candidates.
9. Apply the transport guard at `ModelClient.chat()`, `stream_chat()`, and
   readiness probing before mock or network transport.
10. Fail closed when no general chat agent remains.
11. Leave unknown identifiers eligible without fabricating reasoning, tool, vision,
    or verification capabilities from their names.

This is deliberately a conservative negative filter. A future capability registry
may replace name-based exclusion with authenticated provider metadata, measured
endpoint probes, and separate endpoint-specific pools. Until that evidence exists,
a clearly incompatible model fails closed at transport boundaries and a clearly
specialized policy model fails closed at general-role boundaries.

## Rejected response

Adding `text-embedding-3-large` to a chat fallback map is rejected. It would retain
the invalid primary assignment and merely hide it when a fallback happened to be
available. Repeated provider retries are also rejected because the request is
structurally unsupported, not transiently unavailable.

## Residual operational action

Runtime containment means an already-persisted embedding agent can no longer win
chat selection or failover while stale data is being cleaned up. Durable state must
still converge to the correct exact set: the provider-bootstrap slice owns stale
discovered-agent withdrawal and must import the same shared classifier when rebased.
Runtime rejection is defense in depth, not a substitute for deleting invalid
persistent configuration.

## Verification evidence

`tests/test_chat_model_capability_isolation.py` reproduces the exact Azure model ID
and provider/separator aliases. It verifies:

- OpenAI-compatible and Bytez catalog filtering;
- malformed and prefix-only identifier handling;
- agent-conversion rejection;
- exclusion from the price book and cheapest-agent selection;
- exclusion of a high-priority stale embedding agent from synthesizer selection;
- fail-closed behavior when the persisted pool contains only non-chat agents;
- generated-plan reassignment away from a stale embedding agent;
- exclusion from cross-agent failover;
- direct and streaming `ModelClient` rejection before transport;
- readiness failure with a stable non-chat code before provider access;
- planner inventory and generated-plan isolation;
- distinction between chat-served audio/policy models and general agent roles.

## References

BerriAI. (n.d.). *LiteLLM: Call 100+ LLMs using the OpenAI input/output format*.
Retrieved August 20, 2026, from https://docs.litellm.ai/

Microsoft. (n.d.). *How to switch between OpenAI and Azure OpenAI endpoints*.
Microsoft Learn. Retrieved August 20, 2026, from
https://learn.microsoft.com/en-us/azure/developer/ai/how-to/switching-endpoints

OpenAI. (n.d.). *Data controls in the OpenAI platform: Default usage policies by
endpoint*. Retrieved August 20, 2026, from
https://platform.openai.com/docs/models/default-usage-policies-by-endpoint

OpenAI. (n.d.). *GPT-audio model*. Retrieved August 20, 2026, from
https://developers.openai.com/api/docs/models/gpt-audio
