# Architecture Notes

## Sources Read

- Sakana AI launch article, "Sakana Fugu: One Model to Command Them All" (June 22, 2026): https://sakana.ai/fugu-release/
- Sakana Fugu Technical Report: https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- TRINITY: An Evolved LLM Coordinator: https://arxiv.org/abs/2512.04695
- Learning to Orchestrate Agents in Natural Language with the Conductor: https://arxiv.org/abs/2512.04388
- OpenAI. (2024). *Create chat completion*. OpenAI API reference. https://platform.openai.com/docs/api-reference/chat/create
- OpenAI. (2024). *Create a model response*. OpenAI API reference. https://platform.openai.com/docs/api-reference/responses/create
- OpenAI. (2024). *Streaming API responses*. OpenAI API documentation. https://platform.openai.com/docs/guides/streaming-responses
- OpenAI. (2024). *Streaming events*. OpenAI API reference. https://platform.openai.com/docs/api-reference/responses-streaming
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data interchange format* (RFC 8259). Internet Engineering Task Force. https://doi.org/10.17487/RFC8259

## What The Architecture Is

The public shape is a single model API. The internal shape is a model pool plus a learned coordinator that decides when to answer directly, when to delegate, how much context each worker receives, when to verify, and how to synthesize the final answer.

The useful split is quality-latency, not separate products:

- Low-latency routing: select one worker for the current query or turn.
- Deep orchestration: create a multi-step workflow when the task needs decomposition, independent attempts, verification, or synthesis.

TRINITY contributes the compact coordinator idea: a small model representation plus a lightweight head can choose agent and role over multiple turns. Its Thinker, Worker, and Verifier contracts are practical enough to implement directly.

Conductor contributes the workflow representation: each step is a natural-language subtask, an assigned worker, and an access list of prior step outputs. This is the key piece for preventing every worker from being dragged into the same transcript while still allowing deliberate collaboration.

The Fugu report combines these ideas into production constraints:

- Fugu is optimized for latency by selecting a worker without expensive coordinator generation.
- Fugu-Ultra is optimized for quality by generating deeper workflows over a broader agent pool.
- The agent pool is swappable, allowing provider preference, model exclusion, and compliance controls.
- Multi-agent tool/function-call workflows need memory discipline: isolate agents inside the current workflow, but keep useful shared memory across turns.
- Tool-calling passthrough must be schema-honest: SDK JSON `null` on optional `tool.function` fields is popped before the provider hop so Fugu-style tool workflows do not fail on omit-vs-null mismatches (OpenAI, 2024; Bray, 2017). Assistant `tool_calls` history is similarly fail-closed: only `id`, `type`, `function`, and optional `index` are accepted so unknown keys cannot be smuggled on the single-agent proxy (OpenAI, 2024).

## Implementation Mapping

This repository implements the interface and control plane, not the trained coordinator.

- `contextual_orchestrator.orchestrator.ModelAgent`: one configured worker model.
- `TaskOrchestrator.route_once`: the low-latency routing path.
- `TaskOrchestrator.conduct`: the workflow path with planner, worker, verifier, and synthesizer steps.
- `WorkflowStep.access`: Conductor-style visibility control.
- `ModelClient`: OpenAI-compatible HTTP client, with `mock://` for local checks. `proxy_completion` returns JSON; `proxy_completion_stream` pipes SSE so tool-calling `stream=true` clients receive `chat.completion.chunk` frames (including `delta.tool_calls`) instead of a billed JSON body. `/v1/responses` `stream=true` emits named `response.*` events, including `function_call` argument deltas keyed by `item_id`. Mock function tools emit the same `tool_calls` / `function_call` shape offline so SDK stream parsers can be exercised without a live provider.
- `contextual_orchestrator.server`: small `/v1/chat/completions` and `/v1/responses` HTTP server. Tools and `response_format` take the single-agent passthrough path; `stream=true` on that path is an SSE proxy, not a `400`.

The deliberate simplification is the policy. The paper systems learn routing and topology from rewards; this lab uses deterministic keyword scoring so the repo runs without training data, GPUs, or vendor credentials.

Add learned routing only when there is an evaluation set and logs proving the heuristic policy is the bottleneck.

## Product Planning Interpretation

The product is not a Fugu clone. It is a control-plane prototype for the same public shape: one compatible API with hidden orchestration. The enterprise value comes from exposing the hidden operating evidence:

- pool health and provider exclusion for Fugu-style configurability;
- latency-quality policy for the Fugu versus Fugu-Ultra tradeoff;
- thinker, worker, verifier, and synthesizer roles for TRINITY-style trace review;
- natural-language subtasks and access lists for Conductor-style auditability;
- replayable evaluation runs before any learned coordinator replaces the deterministic policy.

See [product_planning.md](product_planning.md) for the product reboot.
