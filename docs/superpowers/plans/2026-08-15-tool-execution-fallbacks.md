# Tool-execution fallback implementation plan

> Date: 2026-08-15  
> Scope: `contextual-orchestrator` route and Conduct-stage agent invocation

## Problem

The AppGuardrail Strix run `31803400831`, job `94776449119`, failed after the model runtime raised:

```text
Tool execute_command not found in agent strix
```

The existing orchestration path treats every exception as an undifferentiated agent failure. That permits ordinary cross-agent failover, but it cannot distinguish a missing tool from an unsafe replay after a state-changing tool may already have completed. It also cannot retry an explicitly idempotent transient tool call on the same agent.

## Implementation sequence

1. Add failing tests for the exact Strix error and the complete fallback matrix.
2. Introduce structured `ToolExecutionError` metadata and legacy exception classification.
3. Add bounded same-agent retry only for explicitly idempotent transient failures.
4. Fail over missing, unavailable, rate-limited, idempotent execution, and unknown failures as permitted by policy.
5. Fail closed for ambiguous non-idempotent outcomes, invalid arguments, permission denial, and policy denial.
6. Emit secret-free `tool_fallback_decision` audit events.
7. Export the public types and document the decision contract.
8. Verify focused tests, new-module statement/branch coverage, compilation, and repository checks.

## Review-follow-up sequence

1. Add RED tests proving false-like non-booleans cannot select an unverified TLS context and the production HTTP server rejects the development-only TLS opt-out.
2. Add a public `MAX_TOOL_RETRY_ATTEMPTS` policy ceiling and enforce it both at construction and again inside execution so mutated runtime state cannot create unbounded same-agent retries.
3. Bind the hourly dispatch test to the literal `pr-review-fix-scheduler` event type rather than only to a shell variable reference.
4. Keep the insecure provider path available only to explicit non-server development diagnostics; production serving requires system trust or a configured CA bundle.
5. Re-run the focused fallback, TLS, scheduler, and full repository suites before removing the one-shot repair workflow.

## TDD evidence

The initial focused test was executed before implementation and failed during collection because `contextual_orchestrator.tool_fallback` did not exist. After implementation, the same contract test became the required green gate.

The review-follow-up tests were also executed before their implementation and failed because `MAX_TOOL_RETRY_ATTEMPTS` was absent. The verified repair run then recorded 109 focused passes, 405 full-suite passes, successful compilation, and a clean Git diff before deleting its temporary workflow.

## Non-goals

- No automatic aliasing from `execute_command` to a guessed alternative tool name.
- No replay of a non-idempotent operation whose outcome is unknown.
- No endpoint racing or speculative concurrent tool execution.
- No raw provider exception text in audit records or public error messages.
- No insecure TLS opt-out in the production `--serve` path.
- No unbounded retry count configurable by a caller.
