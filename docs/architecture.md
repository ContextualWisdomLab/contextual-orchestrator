# Architecture Notes

## Sources Read

APA 7th citations (titles retained for paper-contract search):

- Sakana AI. (2026, June 22). *Sakana Fugu: One Model to Command Them All*. https://sakana.ai/fugu-release/
- Sakana AI. (2026). *Sakana Fugu Technical Report*. https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *TRINITY: An Evolved LLM Coordinator* (arXiv:2512.04695). https://arxiv.org/abs/2512.04695
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to Orchestrate Agents in Natural Language with the Conductor* (arXiv:2512.04388). https://arxiv.org/abs/2512.04388

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

## Implementation Mapping

This repository implements the interface and control plane, not the trained coordinator.

- `contextual_orchestrator.orchestrator.Agent`: one configured worker model.
- `Orchestrator.route_once`: the low-latency routing path.
- `Orchestrator.conduct`: the workflow path with planner, worker, verifier, and synthesizer steps.
- `WorkflowStep.access`: Conductor-style visibility control.
- `ModelClient`: OpenAI-compatible HTTP client, with `mock://` for local checks.
- `contextual_orchestrator.server`: small `/v1/chat/completions` HTTP server.
  Message honesty fields (`weight`, `prefix`, `refusal`, `annotations`,
  `audio`, `function_call`), role membership (`developer` / `function` /
  unknown roles), content shape (empty user/system, multimodal parts),
  participant `name`, a non-empty `messages` array, `max_tool_calls`,
  a pool `model`, `stream` (SSE passthrough is a follow-up; `stream=true`
  with tools/`response_format` is `invalid_stream`), `stream_options`,
  `attribution`, `routing` (batch / `latency_tolerant=true` fail closed —
  passthrough is sync-only), in-range `temperature` / `top_p` / penalties,
  `max_tokens` / `max_completion_tokens`, `n` (only omit or `1`),
  `seed` (not applied; non-omit is `invalid_seed`), `stop`, `user`,
  `logprobs` / `top_logprobs`, and `logit_bias`
  are validated *before* the tools/response_format passthrough early-return
  so SDK tool-calling bodies cannot smuggle unsupported values, silent-select
  a worker, request unused usage chunks, or bill a JSON completion when the
  client asked for SSE, a batch channel, a multi-choice `n`, or token logprobs.
  Omit-equivalent
  `max_tool_calls` (JSON null / empty string) is stripped, not forwarded.
  Request sampling knobs (`temperature`, `top_p`, penalties, `max_tokens`)
  are applied via `ModelClient.request_sampling` on the calling thread only
  so concurrent Completions/chat and route-stream requests cannot observe
  each other's knobs; `stream_chat` reads the same thread-local overrides.

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
