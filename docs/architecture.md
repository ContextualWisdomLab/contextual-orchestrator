# Architecture Notes

## Sources Read

- Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/
- Sakana AI. (2026). *Fugu technical report*. https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *Trinity: An evolved LLM coordinator*. arXiv. https://arxiv.org/abs/2512.04695
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor*. arXiv. https://arxiv.org/abs/2512.04388

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
- `Orchestrator.route_and_verify` (`mode="verify"`): one worker call plus one checked verifier judgment — for adjudication-shaped requests that need a verified verdict without the full four-step workflow's cost. The verifier must put `ACCEPT` or `REJECT` on the first line (or use those words as whole tokens). Everyday praise, `password`/`looks good` substrings, and negated accepts (`not accepted`) fail closed. A rejected worker answer stays on the trace; sync and SSE surfaces redact `orchestration.verification`.
- `Orchestrator.conduct`: the workflow path with planner, worker, verifier, and synthesizer steps.
- `WorkflowStep.access`: Conductor-style visibility control.
- `reasoning_effort` (request-level only, OpenAI-compatible `minimal`/`low`/`medium`/`high`): threads through every provider call in a request (`ModelClient.chat`/`stream_chat`) so a caller can raise test-time compute for one adjudication without changing embeddings or other cheap calls. This is **not** per-role allocation. Issue #568 remains open for a versioned `reasoning_effort_profile` per thinker/worker/verifier/synthesizer/planner/judge, equal-budget ablation, and the same snapshot on sync, stream, and batch.
- `ModelClient`: OpenAI-compatible HTTP client, with `mock://` for local checks.
- `contextual_orchestrator.server`: small `/v1/chat/completions` HTTP server.

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

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor*. arXiv. https://arxiv.org/abs/2512.04388

Sakana AI. (2026). *Fugu technical report*. https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *Trinity: An evolved LLM coordinator*. arXiv. https://arxiv.org/abs/2512.04695
