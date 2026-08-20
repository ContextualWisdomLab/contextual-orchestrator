# ADR 0001: Safety-aware tool-execution fallback policy

- Status: Proposed
- Date: 2026-08-15
- Decision owners: ContextualWisdomLab

## Context

Model-backed agents can fail before, during, or after invoking a tool. A single “retry everything” rule is unsafe: after a state-changing operation times out, the caller may not know whether the tool completed. Conversely, a model that requests a tool absent from its runtime has not performed a side effect and can be replaced by another eligible agent.

The observed motivating failure was `Tool execute_command not found in agent strix` in AppGuardrail workflow run `31803400831`, job `94776449119`.

## Decision

Introduce a provider-neutral failure classifier with three bounded actions:

```text
retry_same_agent
failover_agent
fail_closed
```

The default matrix is:

| Failure kind | Default action | Rationale |
|---|---|---|
| `tool_not_found` | `failover_agent` | No tool side effect started; another eligible agent may have the capability. |
| `tool_unavailable` | `failover_agent` | Runtime capability is unavailable before execution. |
| `rate_limited` | bounded retry then fail over if idempotent; otherwise fail over | A rejected request can use another endpoint; explicit idempotency permits bounded local retry. |
| `timeout` / `transport_error` | bounded retry then fail over if explicitly idempotent; otherwise `fail_closed` as `ambiguous_outcome` | A non-idempotent request may already have produced a side effect. |
| `invalid_arguments` | `fail_closed` | Repeating the same malformed contract cannot repair it safely. |
| `permission_denied` | `fail_closed` | Agent substitution must not bypass authorization. |
| `policy_blocked` | `fail_closed` | Agent substitution must not bypass policy or approval. |
| `execution_failed` | fail over if explicitly idempotent; otherwise `fail_closed` | A state-changing command must not be duplicated. |
| `ambiguous_outcome` / `outcome_unknown` | always `fail_closed` | The system cannot prove whether a side effect occurred. |
| `unknown` | `failover_agent` | Preserve the existing sequential failover behavior. |

Structured adapters should raise `ToolExecutionError` with a stable failure kind, tool name, idempotency declaration, and outcome certainty. Legacy wrappers are classified from a bounded exception cause chain only when that chain identifies a tool runtime, including the exact Strix missing-tool message. Generic provider transport failures keep the previous agent-failover behavior.

The route and Conduct-stage invocation path performs at most `tool_retry_attempts` same-agent retries, with a shared hard ceiling of four attempts. Exhausted safe retries become sequential agent failover. Every decision emits a secret-free audit record containing only the agent id, failure kind, action, reason code, and retry count.

## Safety invariants

1. Missing-tool handling changes agents; it never guesses an alias for the missing tool.
2. Permission and policy failures never fall through to another agent.
3. Non-idempotent timeout or transport uncertainty never replays automatically.
4. Raw exception messages, command arguments, prompts, tokens, and tool output never enter fallback audit events.
5. Retry count is a nonnegative integer and is bounded per agent invocation.
6. Unknown failures retain pre-existing cross-agent failover compatibility.

## Consequences

### Positive

- The exact `execute_command`-missing failure can recover through another eligible agent.
- Read-only or otherwise idempotent transient tools can recover without immediately abandoning a healthy agent.
- State-changing operations do not duplicate silently after uncertain transport failure.
- Operators receive stable, aggregatable fallback reason codes.

### Negative

- Some non-idempotent requests that might have been safe to repeat will stop for human or caller reconciliation.
- Text classification remains a compatibility bridge; adapters should migrate to structured errors.
- Agent capability matching remains sequential and role-based; endpoint equivalence/racing is outside this ADR.
