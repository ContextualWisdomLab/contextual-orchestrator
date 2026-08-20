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
The current discovery parser accepted every non-empty model identifier and exposed
it to agent creation, price selection, and durable pool synchronization. A catalog
row naming an embedding deployment could therefore be scored for thinker, worker,
verifier, or synthesizer work even though its serving endpoint accepts embedding
input rather than chat messages.

OpenAI documents `text-embedding-3-large` under the embeddings endpoint, separately
from models supported by chat completions. Microsoft likewise demonstrates it with
`client.embeddings.create`, not `client.chat.completions.create`. LiteLLM exposes
chat, responses, embeddings, image, audio, rerank, and other endpoint families as
distinct operations. A router fallback can choose another deployment for the same
operation; it cannot make an embedding deployment execute a chat operation.

## Decision

The ordinary model-discovery module is a **chat-agent discovery boundary**.

1. Normalize provider prefixes and common separators in model identifiers.
2. Reject identifiers that clearly advertise embedding, reranking, transcription,
   moderation/safety, image, audio/speech, realtime, or known embedding-family
   transport semantics.
3. Apply the guard while parsing both OpenAI-compatible and Bytez catalogs.
4. Re-check the invariant before converting a discovery record to `ModelAgent`.
5. Re-check the invariant before writing chat pricing or running price-based chat
   selection.
6. Leave unknown identifiers eligible without fabricating reasoning, tool, vision,
   or verification capabilities from their names.

This is deliberately a conservative negative filter. A future capability registry
may replace name-based exclusion with authenticated provider metadata, measured
endpoint probes, and separate endpoint-specific pools. Until that evidence exists,
a clearly non-chat model fails closed at the chat boundary.

## Rejected response

Adding `text-embedding-3-large` to a chat fallback map is rejected. It would retain
the invalid primary assignment and merely hide it when a fallback happened to be
available. Repeated provider retries are also rejected because the request is
structurally unsupported, not transiently unavailable.

## Residual operational action

This change prevents new incompatible catalog rows from entering the chat pool.
A deployment that already persisted such a row must disable or withdraw that stale
discovered agent. The durable provider-bootstrap slice owns exact-set activation and
stale discovered-agent withdrawal; it must import this shared boundary when rebased.

## Verification evidence

`tests/test_chat_model_capability_isolation.py` reproduces the exact Azure model ID
and provider/separator aliases. It also verifies:

- OpenAI-compatible and Bytez catalog filtering;
- malformed and prefix-only identifier handling;
- agent-conversion rejection;
- exclusion from the price book and cheapest-agent selection.

## References

BerriAI. (2026). *LiteLLM: Call 100+ LLMs using the OpenAI input/output format*.
https://docs.litellm.ai/

Microsoft. (2026). *How to switch between OpenAI and Azure OpenAI endpoints*.
Microsoft Learn. https://learn.microsoft.com/en-us/azure/developer/ai/how-to/switching-endpoints

OpenAI. (2026). *Data controls in the OpenAI platform: Default usage policies by
endpoint*. https://platform.openai.com/docs/models/default-usage-policies-by-endpoint
