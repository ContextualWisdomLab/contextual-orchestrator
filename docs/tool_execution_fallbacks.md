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

### HTTP adapter compatibility

Structured `ToolExecutionError` remains the preferred contract. For legacy tool adapters that expose an `HTTPError`, the classifier inspects the bounded cause chain and applies a conservative status policy:

| HTTP status | Failure kind | Default action |
|---|---|---|
| 400, 406, 411–417, 422, 428, 431 | invalid arguments | fail closed |
| 401, 403, 407, 511 | permission denied | fail closed |
| 404 | tool not found | fail over |
| 405, 410, 426, 501 | tool unavailable | fail over |
| 408, 504 | timeout | retry only when explicitly idempotent |
| 409, 424, 500, 508 | execution failed | fail over only when explicitly idempotent; otherwise fail closed |
| 423, 451 | policy blocked | fail closed |
| 425, 502, 503, 507 | transport error | retry only when explicitly idempotent |
| 429 | rate limited | bounded retry when explicitly idempotent; otherwise fail over |
| unrecognized status | unknown | preserve legacy sequential failover |

A non-idempotent timeout or transport error is reported as `ambiguous_outcome` and fails closed. A non-idempotent `execution_failed` decision also fails closed with action `fail_closed`, reason code `tool_failure.execution_failed.fail_closed`, and `ToolFallbackStoppedError`; the HTTP surface returns the documented `409 tool_execution_stopped` response. HTTP status inference is compatibility behavior only; adapters should provide structured operation semantics whenever possible.

## Retry bound

`TaskOrchestrator(..., tool_retry_attempts=1, tool_retry_backoff_seconds=0.25)` permits one same-agent retry when the classifier marks the operation `retry_safe`. Retries use full-jitter exponential backoff with a 30-second ceiling for each delay. Set `tool_retry_attempts=0` to disable same-agent retries; tests may set the backoff to `0`. Invalid retry counts and negative, non-finite, boolean, or non-numeric backoff values are rejected. The HTTP server deliberately retains the request's concurrency slot during the bounded delay: releasing it would let an unbounded population of sleeping requests bypass `max_concurrent_runs` and later stampede while reacquiring. Workloads that need nonblocking, long-delay retry belong on the durable batch path.

When the retry budget is exhausted, an idempotent transient failure moves to the next eligible agent. Missing/unavailable tools and unknown legacy failures also move directly to the next eligible agent. Circuit-breaker state is updated only after the local retry budget is exhausted.

## Fail-closed errors

`ToolFallbackStoppedError` is raised for ambiguous outcomes, non-idempotent execution failures, and authorization, policy, or argument failures. Its public message contains a stable reason code and agent id only. The original exception remains available as the Python cause for trusted internal diagnostics, but its text is not copied into audit events.

### HTTP and streaming contract

A non-streaming fail-closed decision returns HTTP `409` with OpenAI-shaped error code `tool_execution_stopped`. The error detail contains only the stable action, effective failure kind, reason code, and—when normalization produced `ambiguous_outcome`—the observed timeout or transport kind.

Once streaming response headers have been sent, the server cannot change the HTTP status. It therefore emits the same structured `tool_execution_stopped` error payload as an SSE `data:` frame, follows it with a terminal chunk whose `finish_reason` is `error`, and then emits `[DONE]`. Clients must treat either form as a stopped operation that requires operator reconciliation rather than automatic replay.

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

`failure_kind` is the effective failure kind that determined the action and reason code. When normalization changes that effective kind to `ambiguous_outcome`, `observed_failure_kind` preserves the original normalized timeout or transport cause without retaining raw exception text. The latter field is omitted when it would equal `failure_kind`.

No prompt, tool argument, output, credential, provider response, or exception text is recorded.

## Operator response

- Repeated `tool_not_found`: correct the agent/tool capability inventory; fallback is availability protection, not configuration repair.
- Repeated `rate_limited`: add capacity or change routing policy rather than increasing retries indefinitely.
- `ambiguous_outcome`: reconcile the target system using an idempotency key, operation id, or read-after-write check before retrying.
- `permission_denied` or `policy_blocked`: correct authorization or approval policy; do not add a bypassing fallback.
