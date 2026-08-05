# Architecture Notes

## Sources Read

- Sakana AI launch article, “Sakana Fugu: One Model to Command Them All” (June 22, 2026): https://sakana.ai/fugu-release/
- Sakana Fugu Technical Report: https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- TRINITY: An Evolved LLM Coordinator: https://arxiv.org/abs/2512.04695
- Learning to Orchestrate Agents in Natural Language with the Conductor: https://arxiv.org/abs/2512.04388
- Scaling LLM Test-Time Compute Optimally Can Be More Effective Than Scaling Model Parameters: https://arxiv.org/abs/2408.03314
- RouteLLM: Learning to Route LLMs with Preference Data: https://arxiv.org/abs/2406.18665
- FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance: https://arxiv.org/abs/2305.05176
- ISO/IEC 23894:2023 and ISO/IEC 42001:2023.
- Current official OpenAI, NVIDIA NIM, and Gemini reasoning-control documentation.

See `docs/doctoring/adaptive-reasoning-control.md` for the source-to-design trace and APA 7th references.

## What The Architecture Is

The public shape is a single model API. The internal shape is a model pool plus a learned-coordinator-compatible control plane that decides when to answer directly, when to delegate, how much context each worker receives, when to verify, how to synthesize, and how much model-native reasoning compute each call should receive.

The useful split is compute allocation, not separate products:

- **Model allocation:** select one worker and exhaust eligible free fallbacks before paid candidates.
- **Topology allocation:** use low-overhead routing or a deeper workflow with bounded steps, subtasks, recursive planning, and access lists.
- **Reasoning allocation:** select the least costly supported reasoning level justified for each role and task, then escalate once only when verification rejects the worker result.

TRINITY contributes the compact coordinator idea: a small model representation plus a lightweight head can choose agent and role over multiple turns. Its Thinker, Worker, and Verifier contracts are practical enough to implement directly.

Conductor contributes the workflow representation: each step is a natural-language subtask, an assigned worker, and an access list of prior step outputs. This prevents every worker from receiving the same transcript while permitting deliberate collaboration.

Fugu combines these ideas into production constraints:

- one compatible API hides model-pool orchestration;
- low-overhead routing and deeper quality-oriented orchestration remain selectable;
- the agent pool is swappable for provider, compliance, and availability constraints;
- recursive and multi-agent work needs bounded memory and explicit visibility.

Adaptive reasoning control adds the missing within-model compute dimension. Provider capability is explicit configuration. The runtime never assumes that two models accept the same effort vocabulary or payload path.

## Implementation Mapping

This repository implements the interface and control plane, not the trained coordinator.

- `contextual_orchestrator.orchestrator.ModelAgent`: one configured worker model.
- `TaskOrchestrator.route_once`: low-topology-compute routing.
- `TaskOrchestrator.conduct`: planner, worker, verifier, and synthesizer workflow.
- `WorkflowStep.access`: Conductor-style visibility control.
- `model_fallback`: deterministic free-first candidate eligibility and ordering.
- `reasoning_control`: provider-neutral profiles, policies, decisions, payload rules, token evidence, and ablation cells.
- `reasoning_runtime`: idempotent integration across agent configuration, admin views, provider calls, failover, streaming, Responses passthrough, Batch, workflow traces, verifier escalation, and ablation.
- `provider_transport`: DNS-pinned HTTPS egress with original-host TLS verification, no environment proxy, and redirect rejection.
- `contextual_orchestrator.server`: compatible API and admin control plane.

The deliberate simplification remains the coordinator policy. The paper systems learn routing and topology from rewards; this lab uses deterministic policy so the repository runs without training data, GPUs, or vendor credentials. Learned routing should be added only after replayable evaluations and logs show the deterministic policy is the bottleneck.

## Adaptive Reasoning Data Flow

```text
request
  → route/conduct and role selection
  → canonical ReasoningDecision
  → candidate-specific capability projection
  → endpoint-specific payload mapping
  → provider call through pinned transport
  → provider usage parsing
  → bounded trace evidence
  → verifier rejection? one next-level worker retry
  → affected verifier/synthesizer recomputation
```

Caller-owned reasoning fields are never overwritten. Custom mappings are safe nested paths plus fixed scalar templates; they cannot execute expressions. Hidden private intermediate reasoning content is not persisted.

## Failure and Compatibility Semantics

- An agent without a reasoning profile preserves legacy request shape.
- An unsupported canonical level projects downward to the nearest declared level.
- A failover model remaps the canonical decision instead of inheriting another provider’s payload.
- Invalid custom paths or mappings fail at configuration time.
- A verifier retry is limited to one immediate higher supported level.
- No higher level, a disabled strategy, or a zero escalation cap means no retry.
- Admin patch operations preserve a profile across frozen-dataclass replacement and re-save it through the configured pool store.

## Product Planning Interpretation

The product is not a Fugu clone. It is a control plane for the same public shape: one compatible API with hidden but auditable orchestration. Enterprise value comes from exposing operating evidence:

- pool health, visibility, cost tier, credential requirements, and provider exclusion;
- direct-versus-deep topology decisions;
- thinker, worker, verifier, and synthesizer traces;
- natural-language subtasks and access lists;
- role-specific reasoning decisions, caps, escalation, and token use;
- fixed-effort ablations before production policy changes;
- replayable task evaluations before any learned coordinator replaces deterministic policy.

See `docs/product_planning.md` for the broader product reboot and `docs/reasoning-control.md` for the subsystem contract.
