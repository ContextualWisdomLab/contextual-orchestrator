# ADR 0001: Safety-aware tool-execution fallback policy

- Status: Accepted
- Date: 2026-08-15
- Citation alignment: 2026-08-25
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

## Amendment (2026-08-30): explicit provider-transport classification

The primary model call `TaskOrchestrator._invoke` makes on every route/Conduct step (`ModelClient.chat`) is a bounded, side-effect-free read: it is a model completion request, not a tool invocation, so it can never produce the ambiguous-outcome risk this ADR's `fail_closed` rows exist to guard against. Before this amendment, that call's already-typed `ProviderUpstreamError` (see `contextual_orchestrator.provider_errors`) was still routed through the same message-text classifier this ADR defines for tool runtimes. In practice a generic transport error rarely mentions a tool-runtime keyword, so it fell through to the `unknown` row and correctly kept failing over — but only incidentally: an upstream error body that happened to also say, for example, "invalid arguments" (a phrase also used by ordinary 400s unrelated to any tool) would have been misclassified into this ADR's `invalid_arguments`/`fail_closed` row and stopped free/auto virtual-model failover on a request that had never touched a tool.

`contextual_orchestrator.tool_fallback.classify_provider_transport_failure(retryable: bool)` now classifies this specific call directly from the provider taxonomy's own already-computed `retryable` flag — never from message text — and never returns `fail_closed`: retryable failures (429/500/502/503/504/408/network) get one bounded same-agent retry then sequential failover; non-retryable failures (401/403/404/413 handled earlier/422/...) fail over immediately. This is the same "generic provider transport failures keep the previous agent-failover behavior" intent this ADR already stated; it is now an explicit, provider-status-driven contract instead of an implicit one that depended on a failure message never mentioning a tool-fallback keyword. `classify_tool_failure` itself is unchanged and still governs genuine `ToolExecutionError` adapters and the provider's own explicit `tool_execution_stopped` signal (`_provider_tool_execution_stopped`), both of which keep failing closed exactly as this ADR specifies. Motivated by the `orchestrator/free` review-sidecar reliability gap tracked in `ContextualWisdomLab/.github` PR #1433.

## Amendment (2026-08-31): a caller-scoped combined deadline

Diagnosed against `contextual-orchestrator#946`'s `noema-review` `TimeoutError` failures (four consecutive commits, live job-log confirmed): this ADR's `retry_same_agent` bound and `_invoke`'s cross-candidate failover loop each have their own bounded budget, but nothing bounds their *sum*, and nothing lets a caller relate that sum to its own fixed external deadline. Enumerated on `main` at the time of this amendment: `ModelClient._send_with_retry`'s own internal transport retry (`max_retries + 1` attempts at `timeout` seconds each) already stacks with this ADR's `retry_same_agent` action for the identical retryable-transport-failure classification (`classify_provider_transport_failure(True)`) — two independent layers retrying the same failure class against the same agent — before `_invoke`'s `for agent in candidates:` loop even starts failing over to a *different* agent with no combined ceiling of its own. With the review sidecar's actual (un-tuned) serving configuration (`ModelClient(timeout=90, max_retries=2)`, `TaskOrchestrator(tool_retry_attempts=1)` — its launcher passes no overrides for the serving path, unlike its deliberately-bounded preflight client), a single candidate agent's worst case alone (`2 × (3×90 + 1.5s) ≈ 543s`) is already 4.5x a fixed 120s external caller timeout, before cross-candidate failover (up to the sidecar's own 12-route catalog) is even considered.

`TaskOrchestrator.route_once(..., deadline_seconds=...)` adds an opt-in, additive parameter (threaded into `_invoke` as an absolute `deadline`) bounding the combined wall-clock time across both of this ADR's retry layers plus cross-candidate failover to a caller-chosen ceiling. It changes no existing default (`ModelClient.timeout`/`max_retries`, `TaskOrchestrator.tool_retry_attempts` are untouched) and is a pure no-op for any caller that leaves it `None`, which remains every caller as of this amendment: the actual review-sidecar fix (tuning its serving `ModelClient`/`TaskOrchestrator` construction, and/or raising `noema_review_gate.py`'s external timeout, both in `ContextualWisdomLab/.github`) is still outstanding in that repository and is not part of this amendment. Safety invariants 3 and 5 above are preserved: a deadline never interrupts an attempt already in flight (no new non-idempotent replay risk), and it can only *reduce* the number of attempts a fully-unbounded run would otherwise make, never increase it.

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

## Citation alignment

The fallback matrix is unchanged. Verified sources below confirm the existing
retry and fail-closed rules; they do not require a different action table.

- RFC 9110 §9.2.1 defines *safe* methods as essentially read-only: the client
  does not request a state change (Fielding et al., 2022, section 9.2.1).
  RFC 9110 §9.2.2 defines *idempotent* methods as those whose intended server
  effect of multiple identical requests equals the effect of one, and says a
  client **SHOULD NOT** automatically retry a non-idempotent method unless it
  knows the semantics are actually idempotent or can detect that the original
  request was never applied (Fielding et al., 2022, section 9.2.2). That is
  why this ADR retries or fails over only when the adapter declares
  idempotency, and why timeout or transport uncertainty on a non-idempotent
  call is `fail_closed` as `ambiguous_outcome`.
- NIST SP 800-53 Rev. 5 control **SI-11** (Error Handling) requires error
  messages that support corrective action without revealing information that
  adversaries could exploit, and restricts those messages to authorized
  roles (Joint Task Force, 2020, SI-11). That is why fallback audit events
  carry only agent id, failure kind, action, reason code, and retry count.
- NIST SP 800-53 Rev. 5 control **SC-24** (Fail in Known State) requires
  failing to an organization-defined known state and preserving defined
  state information so confidentiality, integrity, or availability is not
  lost in failure (Joint Task Force, 2020, SC-24). This ADR's `fail_closed`
  actions are that known safe stop: do not replay, do not substitute an
  unauthorized agent, and do not guess a tool alias.
- NIST SP 800-204 discusses **circuit breakers** and the **fail-fast**
  isolation of an instance that exceeds a failure threshold; it does **not**
  use the phrase fail-closed (Chandramouli, 2019). This ADR cites 800-204
  only for bounded isolation after repeated failure (same-agent retry
  budget, then sequential failover). Fail-closed itself is grounded in
  RFC 9110 §9.2.2 and SP 800-53 SC-24 / SI-11, not in 800-204.

## References

Chandramouli, R. (2019). *Security strategies for microservices-based
application systems* (NIST Special Publication 800-204). National Institute
of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-204

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force.
https://doi.org/10.17487/RFC9110

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53, Rev. 5).
National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5
