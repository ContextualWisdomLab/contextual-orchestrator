# ADR-0001: Route and conduct test-time compute

## Status

`implemented_on_protected_main`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers
**Scope:** `TaskOrchestrator.complete()`, `route`, and `conduct` on the
OpenAI-compatible chat surface. This ADR does not claim a trained coordinator
or a published ICLR proceedings implementation.

## Context and decision drivers

One compatible endpoint must handle simple requests economically and complex
requests with explicit decomposition and verification. Three verified sources
motivate complementary pieces of that split. None of them is implemented as a
learned system in this repository.

Xu et al. (2026) describe TRINITY as a compact coordinator that assigns
Thinker, Worker, and Verifier roles over a bounded number of turns. Nielsen et
al. (2026) describe Conductor workflows as natural-language subtasks, assigned
workers, and access lists of prior step outputs. Tang et al. (2026) and
Sakana AI (2026) describe Fugu as a latency-oriented worker-selection path and
Fugu-Ultra as a deeper quality-oriented workflow over a swappable agent pool.

Those papers are versioned arXiv preprints. Xu et al. and Nielsen et al. carry
arXiv comments that they are “to appear” at ICLR 2026. This ADR cites the
verified preprint versions and does **not** treat those comments as a final
proceedings record.

Correctness, inspectable evidence, controllability, reliability, and
comparable budgets are primary drivers. Latency is a measured guardrail, not a
license to skip verification on hard tasks or to spend extra calls on every
request.

## Considered alternatives

- Always call one model: simple and cheap, but cannot expose structured
  verification or multi-agent evidence.
- Always run a fixed multi-agent workflow: auditable, but wastes compute and
  confounds quality comparisons.
- Train a learned coordinator immediately: unsupported without a versioned
  evaluation set and operational reward data. Xu et al. (2026) and Nielsen et
  al. (2026) learn routing; this lab does not.
- Deterministic route/conduct split with a measurable policy: selected.

## Decision

`TaskOrchestrator.complete()` chooses `route` or `conduct` from an explicit
caller mode and a snapshotted policy.

- **Route** selects one eligible worker for simple or latency-sensitive work.
  This is the Fugu-style fast path (Tang et al., 2026; Sakana AI, 2026).
- **Conduct** executes a bounded workflow with explicit roles and access
  lists. Role names `thinker`, `worker`, and `verifier` follow TRINITY
  contracts (Xu et al., 2026). Access lists follow Conductor visibility
  control (Nielsen et al., 2026). A synthesizer step is a product addition
  for a single public answer, not a fourth TRINITY paper role.

The paper systems learn routing and topology from rewards. This repository
uses deterministic keyword scoring so the lab runs without training data,
GPUs, or vendor credentials. Add learned routing only when an evaluation set
and logs prove the heuristic policy is the bottleneck.

New recursion, topology, or reasoning-effort knobs require hard call/token
caps and comparable-budget ablations before they become a default.

## Consequences

The standalone runtime stays deterministic and testable. Deep orchestration
may improve difficult tasks but costs more and cannot honestly token-stream a
synthesizer that has not run. Policy changes require evaluation replay.
Paper-inspired role names remain source terminology and are naming-rule
exceptions.

## Failure and recovery

Invalid generated plans, when introduced, fall back to the bounded template.
Budget exhaustion fails before extra provider calls. If conduct quality is not
better under a comparable budget, revert affected workload cells to route or
the last accepted policy.

## Security, privacy, and governance impact

More steps create more provider exposure. Access lists, call bounds, provider
exclusions, and purpose-bound payload minimization apply to every step (NIST,
2024a; International Organization for Standardization, 2023b). A deeper
workflow never expands tool or credential authority.

## Compatibility and migration

The public API remains one model-like surface (`/v1/chat/completions`). New
policy fields default to current deterministic behavior and require trace
versioning.

## Verification and acceptance

`tests/test_paper_contracts.py` encodes the Fugu route/conduct split, TRINITY
role order, and Conductor access-list visibility. Learned replacement
additionally needs repeatable superiority over the deterministic baseline
under a locked budget.

## Rollback and supersession

Rollback selects the prior policy without changing request schema. Supersede
only with an ADR that documents evaluation data, budget parity, failure
behavior, and migration.

## References

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H.,
Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., &
Clanuwat, T. (2026). *Sakana Fugu technical report* (arXiv:2606.21228,
Version 2) [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2606.21228

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026).
*TRINITY: An evolved LLM coordinator* (arXiv:2512.04695, Version 3)
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04695

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2026).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388, Version 5) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04388

National Institute of Standards and Technology. (2024a). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

International Organization for Standardization. (2023b). *Information
technology — Artificial intelligence — Management system* (ISO/IEC
42001:2023). https://www.iso.org/standard/81230.html

See also [docs/REFERENCES.md](../REFERENCES.md).
