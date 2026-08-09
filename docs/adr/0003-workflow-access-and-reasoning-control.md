# ADR-0003: Explicit workflow access and role reasoning control

## Status

`accepted_architecture` — explicit workflow steps/access lists are
`implemented_on_protected_main`; adaptive role-specific reasoning is
`active_pr` in #99.

## Context and decision drivers

Multi-agent quality depends on topology, task decomposition, worker assignment,
and information flow. Giving every worker the whole transcript increases cost,
PII exposure, prompt-injection reach, and correlated error. Conductor and
TRINITY provide useful explicit workflow/role abstractions.

## Considered alternatives

- shared full transcript: easiest, but violates least context;
- fixed four steps only: deterministic, but not task-adaptive;
- unrestricted generated workflows: flexible, but unsafe and unbounded;
- bounded validated plans with explicit access and optional reviewed effort
  profiles: selected.

## Decision

Every workflow step declares role, agent, natural-language subtask, and prior
step IDs it may access. Generated plans are structurally validated and bounded;
invalid plans use the template. Reasoning effort, recursion, and decomposition
are policy values, not provider-output authority, and must preserve common
budgets in evaluations.

## Consequences

Information flow is inspectable and testable. Some useful context must be
deliberately listed. Provider-specific effort mappings remain adapters behind a
provider-neutral profile.

## Failure and recovery

Unknown agents, forward references, cycles, invalid roles, excessive depth, or
budget overflow reject/fallback before execution. A faulty effort adapter falls
back to the last accepted profile, not an unbounded provider default.

## Security, privacy, and governance impact

Access lists reduce unnecessary PII and hostile-output propagation. They do not
sanitize visible content or grant tools; integrating hosts still enforce purpose
and tool authority.

## Compatibility and migration

Existing template workflows remain the default. New profile fields are optional
and trace-versioned. #99 evidence does not transfer before its stack merges.

## Verification and acceptance

Access-list visibility tests, plan parser/property tests, cycle/forward-reference
rejection, per-role payload tests, comparable-budget ablations, and exact-head
coverage are required.

## Rollback and supersession

Disable generated/adaptive policy and return to the bounded template. Supersede
only with a flow-control model that preserves explicit inspectable authority.

## References

Nielsen et al. (2025); Xu et al. (2025); Fugu Team, Sakana AI (2026). See
[the reference index](../REFERENCES.md).
