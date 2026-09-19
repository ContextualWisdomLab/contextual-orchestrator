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

## TDD evidence

The focused test was executed before implementation and failed during collection because `contextual_orchestrator.tool_fallback` did not exist. After implementation, the same contract test is the required green gate.

## Non-goals

- No automatic aliasing from `execute_command` to a guessed alternative tool name.
- No replay of a non-idempotent operation whose outcome is unknown.
- No endpoint racing or speculative concurrent tool execution.
- No raw provider exception text in audit records or public error messages.
