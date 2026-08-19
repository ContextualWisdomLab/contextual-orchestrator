# Architecture Notes

## Sources Read

- Sakana AI launch article, "Sakana Fugu: One Model to Command Them All" (June 22, 2026): https://sakana.ai/fugu-release/
- Sakana Fugu Technical Report: https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- TRINITY: An Evolved LLM Coordinator: https://arxiv.org/abs/2512.04695
- Learning to Orchestrate Agents in Natural Language with the Conductor: https://arxiv.org/abs/2512.04388
- Route to Reason: Adaptive Routing for LLM and Reasoning Strategy Selection: https://arxiv.org/abs/2505.19435
- Route-and-Reason: Scaling Large Language Model Reasoning with Reinforced Model Router: https://arxiv.org/abs/2506.05901
- Reasoning on a Budget: A Survey of Adaptive and Controllable Test-Time Compute in LLMs: https://arxiv.org/abs/2507.02076
- Ares: Adaptive Reasoning Effort Selection for Efficient LLM Agents: https://arxiv.org/abs/2603.07915

## What The Architecture Is

The public shape is a single model API. The internal shape is a model pool plus
an orchestrator that decides when to answer directly, when to delegate, how
much context each worker receives, when to verify, and how to synthesize the
final answer. The public `contextual-orchestrator` model is the orchestration
candidate; the configured local and remote models are worker candidates in its
pool. The candidate registry retains every discovered model. `disabled` is an
explicit operator/admin quarantine or removal state, not an automatic discovery
result. Capability and recursion constraints are expressed separately from that
state.

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

This repository implements the interface and control plane, not the trained
coordinator or its optional recursive self-worker. The public model is therefore
an explicit control-plane candidate, while the worker pool is selected from
configured `ModelAgent` records. The current implementation keeps that public
record out of internal roles with provider exclusions until the runtime has a
bounded, authenticated recursion protocol; it is not administratively disabled.

- `contextual_orchestrator.orchestrator.Agent`: one configured worker model.
- `Orchestrator.route_once`: the low-latency routing path.
- `Orchestrator.conduct`: the workflow path with planner, worker, verifier, and synthesizer steps.
- `WorkflowStep.access`: Conductor-style visibility control.
- `ModelClient`: OpenAI-compatible HTTP client, with `mock://` for local checks.
- `contextual_orchestrator.server`: small `/v1/chat/completions` HTTP server.

The deliberate simplification is the policy. The paper systems learn routing
and topology from rewards; this lab uses capability evidence and a bounded
orchestrator policy, with `auto` kept internal rather than sent as a provider
value. This is never an answer-quality, verification, or accept/reject
judgment: verifier decisions must use the structured model judge and fail
closed (see [ADR 0001](planning/adrs/0001-fail-closed-model-judgment.md)).

Model and reasoning changes are governed by [ADR
0011](planning/adrs/0011-paper-grounded-adaptive-reasoning-policy.md). The
provider-neutral gateway boundary and direct-MLX prohibition are governed by
[ADR 0010](planning/adrs/0010-gateway-only-provider-contract.md).

Add learned routing only when there is an evaluation set and logs proving the heuristic policy is the bottleneck.

## Product Planning Interpretation

The product is not a Fugu clone. It is a control-plane prototype for the same public shape: one compatible API with hidden orchestration. The enterprise value comes from exposing the hidden operating evidence:

- pool health and provider exclusion for Fugu-style configurability;
- latency-quality policy for the Fugu versus Fugu-Ultra tradeoff;
- thinker, worker, verifier, and synthesizer roles for TRINITY-style trace review;
- natural-language subtasks and access lists for Conductor-style auditability;
- replayable evaluation runs before any learned coordinator replaces the deterministic policy.

See [product_planning.md](product_planning.md) for the product reboot.
