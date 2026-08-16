# Architecture Notes

## Sources Read

APA 7th citations (titles retained for paper-contract search):

- Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/
- Sakana AI. (2026). *Sakana Fugu Technical Report*. https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *Trinity: An evolved LLM coordinator* (arXiv:2512.04695). https://arxiv.org/abs/2512.04695
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor* (arXiv:2512.04388). https://arxiv.org/abs/2512.04388
- OpenAI. (2024). *Create chat completion*. OpenAI API reference. https://platform.openai.com/docs/api-reference/chat/create
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data interchange format* (RFC 8259). Internet Engineering Task Force. https://doi.org/10.17487/RFC8259
- Joint Task Force. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53 Rev. 5). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5
- International Organization for Standardization. (2022). *Information security, cybersecurity and privacy protection — Information security controls* (ISO/IEC 27001:2022). https://www.iso.org/standard/27001

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
- Tool-calling passthrough must be schema-honest: SDK JSON `null` on optional `tool.function` fields is popped before the provider hop so Fugu-style tool workflows do not fail on omit-vs-null mismatches (OpenAI, 2024; Bray, 2017).

## Implementation Mapping

This repository implements the interface and control plane, not the trained coordinator.

- `contextual_orchestrator.orchestrator.Agent`: one configured worker model.
- `Orchestrator.route_once`: the low-latency routing path.
- `Orchestrator.conduct`: the workflow path with planner, worker, verifier, and synthesizer steps.
- `WorkflowStep.access`: Conductor-style visibility control.
- `ModelClient`: OpenAI-compatible HTTP client, with `mock://` for local checks.
  Provider host allowlisting (`provider_egress.allowed_provider_hosts`) is
  read from the process KV at request time (NIST SP 800-53 Rev. 5 SC-7;
  ISO/IEC 27001:2022 A.8.20). `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS`
  is bootstrap transport into that KV key only — never `os.getenv` during
  `_validate_provider`.
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
