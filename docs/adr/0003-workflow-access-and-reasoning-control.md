# ADR-0003: Explicit workflow access and role control

## Status

`implemented_on_protected_main` for explicit workflow steps, roles, and
access lists.

Adaptive, provider-native reasoning-effort profiles and unrestricted generated
topologies are **not** shipped on protected `main` and must not be described
as implemented.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Multi-agent quality depends on topology, task decomposition, worker
assignment, and information flow. Giving every worker the whole transcript
increases cost, PII exposure, prompt-injection reach, and correlated error
(OWASP Foundation, 2025; National Institute of Standards and Technology,
2024a).

Nielsen et al. (2026) represent each Conductor step as a natural-language
subtask, an assigned worker, and an access list of prior step outputs. That
access list is the concrete mechanism this repository implements. Xu et al.
(2026) contribute explicit Thinker, Worker, and Verifier contracts. Tang et
al. (2026) add the production constraint that multi-agent tool workflows need
memory discipline: isolate agents inside the current workflow, keep useful
shared memory across turns.

Those papers remain versioned preprints. “To appear at ICLR 2026” is an arXiv
comment, not a final proceedings citation.

## Considered alternatives

- Shared full transcript: easiest, but violates least context.
- Fixed four steps only, with no access lists: deterministic, but not
  inspectable for who saw what.
- Unrestricted generated workflows: flexible, but unsafe and unbounded.
- Bounded template workflows with explicit access lists: selected.

## Decision

Every workflow step declares a role, an agent, a natural-language subtask, and
the prior step IDs it may access. `WorkflowStep.access` is the Conductor-style
visibility control (Nielsen et al., 2026). Protected `main` uses a bounded
template (`thinker → worker → verifier → synthesizer`). Generated plans, when
added later, must be structurally validated and bounded; invalid plans use the
template.

Reasoning effort, recursion, and decomposition are policy values, not
provider-output authority. They must preserve common budgets in evaluations
before they become defaults.

## Consequences

Information flow is inspectable and testable. Some useful context must be
deliberately listed. Provider-specific effort mappings, if added, remain
adapters behind a provider-neutral profile.

## Failure and recovery

Unknown agents, forward references, cycles, invalid roles, excessive depth, or
budget overflow reject or fall back before execution. A faulty effort adapter
falls back to the last accepted profile, not an unbounded provider default.

## Security, privacy, and governance impact

Access lists reduce unnecessary PII and hostile-output propagation
(International Organization for Standardization, 2022, 2023b). They do not
sanitize visible content or grant tools. Integrating hosts still enforce
purpose and tool authority.

## Compatibility and migration

Existing template workflows remain the default. New profile fields are
optional and trace-versioned.

## Verification and acceptance

`tests/test_paper_contracts.py` asserts that a worker sees only listed prior
outputs and that a verifier can see both planner and worker outputs. Plan
parser, cycle, and comparable-budget tests are required before generated
topologies ship.

## Rollback and supersession

Disable generated or adaptive policy and return to the bounded template.
Supersede only with a flow-control model that preserves explicit inspectable
authority.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2026).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388, Version 5) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026).
*TRINITY: An evolved LLM coordinator* (arXiv:2512.04695, Version 3)
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04695

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H.,
Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., &
Clanuwat, T. (2026). *Sakana Fugu technical report* (arXiv:2606.21228,
Version 2) [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2606.21228

National Institute of Standards and Technology. (2024a). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

International Organization for Standardization. (2022). *Information
security, cybersecurity and privacy protection — Information security
management systems — Requirements* (ISO/IEC 27001:2022).
https://www.iso.org/standard/27001

International Organization for Standardization. (2023b). *Information
technology — Artificial intelligence — Management system* (ISO/IEC
42001:2023). https://www.iso.org/standard/81230.html

OWASP Foundation. (2025). *OWASP Top 10 for large language model
applications 2025*. https://owasp.org/www-project-top-10-for-large-language-model-applications/

See also [docs/REFERENCES.md](../REFERENCES.md).
