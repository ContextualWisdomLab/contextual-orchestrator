# ADR 0003: Trinity roles and Conductor workflows

- Status: Accepted
- Date: 2026-08-16

## Context

A single-worker chat call is not enough when a task needs planning,
independent implementation, verification, and a final assembled answer.
Dumping the full transcript into every worker wastes context and leaks
intermediate drafts that a given step should not see.

Trinity contributes practical **Thinker, Worker, and Verifier** contracts: a
coordinator assigns a role and a worker over multiple turns. Conductor
contributes the workflow object: each step is a natural-language subtask, an
assigned worker, and an **access list** of prior outputs.

## Decision

On the deep path (`conduct`), build a short natural-language workflow:

1. **thinker** — plan the work (Trinity).
2. **worker** — execute the assigned subtask (Trinity).
3. **verifier** — check the accumulated answer (Trinity).
4. **synthesizer** — assemble the caller-facing answer. This role is **this
   lab's addition**, not a Trinity paper claim.

Each `WorkflowStep` carries a Conductor-style access list so a worker sees
only the prior outputs deliberately exposed to it. Traces record role, worker,
subtask, access list, and verifier outcome for operator review.

## Consequences

- Conducted traces are auditable without making every worker a party to every
  prior draft.
- The synthesizer step means conduct mode cannot honestly token-stream a
  final answer until the workflow finishes; route mode can stream live.
- Replacing the deterministic planner with a trained Trinity/Conductor
  coordinator is out of scope until evaluation replay shows the heuristic
  policy is the bottleneck.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor*. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *Trinity: An evolved LLM coordinator*. arXiv. https://doi.org/10.48550/arXiv.2512.04695
