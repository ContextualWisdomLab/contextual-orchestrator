# Tool execution fallbacks

`contextual-orchestrator` distinguishes tool failures that can be retried or moved to another agent from failures that must stop safely.

## Structured adapter contract

Tool adapters should raise `ToolExecutionError` instead of flattening every failure into a generic `RuntimeError`:

```python
from contextual_orchestrator import ToolExecutionError, ToolFailureKind

raise ToolExecutionError(
    "read operation timed out",
    tool_name="inspect_repository",
    kind=ToolFailureKind.TIMEOUT,
    idempotent=True,
)
```

`idempotent=True` is an explicit replay-safety declaration. It must not be set merely because a tool usually reads data. The adapter must know that repeated identical calls have the same intended externally visible effect.

Set `outcome_unknown=True` whenever a state-changing call may have completed but its acknowledgement was lost. That condition always fails closed.

## Legacy error compatibility

The classifier also recognizes bounded message patterns from wrapped agent frameworks when the exception chain identifies a tool, command, MCP runtime, function call, or sandbox. Generic provider transport failures remain on the pre-existing cross-agent failover path. In particular:

```text
Tool execute_command not found in agent strix
```

maps to:

```text
failure_kind = tool_not_found
action       = failover_agent
```

The classifier follows at most eight exception cause/context links. The collected text is used only in memory for classification and is not returned or audited.

## Retry bound

`TaskOrchestrator(..., tool_retry_attempts=1)` permits one same-agent retry when the classifier marks the operation `retry_safe`. Set the value to `0` to disable same-agent retries while retaining safe cross-agent fallback. Boolean, negative, non-integer, and fractional values are rejected.

When the retry budget is exhausted, an idempotent transient failure moves to the next eligible agent. Missing/unavailable tools and unknown legacy failures also move directly to the next eligible agent. Circuit-breaker state is updated only after the local retry budget is exhausted.

## Fail-closed errors

`ToolFallbackStoppedError` is raised for ambiguous outcomes and authorization, policy, or argument failures. Its public message contains a stable reason code and agent id only. The original exception remains available as the Python cause for trusted internal diagnostics, but its text is not copied into audit events.

## Audit event

Each fallback decision records:

```json
{
  "event_type": "tool_fallback_decision",
  "event_detail": {
    "agent_id": "primary_worker",
    "action": "failover_agent",
    "failure_kind": "tool_not_found",
    "reason_code": "tool_failure.tool_not_found.failover_agent",
    "retry_attempt": 0
  }
}
```

No prompt, tool argument, output, credential, provider response, or exception text is recorded.

## Operator response

- Repeated `tool_not_found`: correct the agent/tool capability inventory; fallback is availability protection, not configuration repair.
- Repeated `rate_limited`: add capacity or change routing policy rather than increasing retries indefinitely.
- `ambiguous_outcome`: reconcile the target system using an idempotency key, operation id, or read-after-write check before retrying.
- `permission_denied` or `policy_blocked`: correct authorization or approval policy; do not add a bypassing fallback.
