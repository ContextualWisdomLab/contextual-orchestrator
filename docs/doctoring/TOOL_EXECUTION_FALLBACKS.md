# Doctoring: tool-execution retry and fallback

## Standards traceability

The fallback policy treats replay safety as an explicit semantic property, not as a guess derived from an exception string. RFC 9110 defines idempotency by whether repeated identical requests have the same intended effect, permits automatic replay after communication failure for idempotent requests, and cautions against automatically retrying non-idempotent requests unless the implementation can prove idempotency or prove that the original request was not applied.

The implementation generalizes that principle beyond HTTP methods to model tools: timeout and transport failures retry only when a tool adapter explicitly declares replay safety. If a non-idempotent operation may have completed, the orchestrator returns an ambiguous-outcome failure rather than duplicating the side effect.

NIST AI 600-1 frames generative-AI risk management around governance, measurement, pre-deployment testing, incident disclosure, security, resilience, accountability, and transparency. The implementation supports those objectives through deterministic failure categories, bounded actions, fail-closed authorization/policy behavior, regression tests, and secret-free audit evidence.

## Design-to-source map

| Product decision | Source basis | Implementation |
|---|---|---|
| Retry only when replay is known safe | RFC 9110 §9.2.2 | `idempotent` metadata gates `retry_same_agent`. |
| Stop when a non-idempotent result might already have occurred | RFC 9110 §9.2.2 | Non-idempotent timeout/transport uncertainty and `outcome_unknown` map to `ambiguous_outcome` + `fail_closed`; non-idempotent execution failure also fails closed. |
| Test and measure failure behavior | NIST AI 600-1 | Exact Strix regression plus statement/branch coverage. |
| Preserve accountability without disclosing sensitive content | NIST AI 600-1 | Stable reason codes and secret-free audit events. |
| Do not bypass policy through fallback | NIST AI 600-1 | Permission and policy failures always `fail_closed`. |

## Virtual-worker handoff regression (2026-09-08)

At PR #1094 head `1c61eff2da012382255bf8b4e1aa6dd0d6dd05ca`, a valid
worker tool request with empty text was judged as a failed answer in route mode
and lost before the next role in conduct mode. Buffered stream framing also
omitted tool-call indices. These defects can prevent review agents from using
the tools they need to inspect a pull request.

The repair in `0246e98e69f2da56f5aa38ce071ae9cda78169c3` returns the worker
handoff before text judging or later roles, preserves conduct persistence, and
adds missing stream indices without mutating supplied objects. A handoff means
the caller must execute the tool; it is not evidence of a completed answer or a
positive text-quality observation. Replay safety still follows the policy above.
Progress hooks honor positional, keyword-only, and keyword-rest signatures.

From a checkout with project-local `.venv` and its test dependencies installed:

```sh
uv run --no-project .venv/bin/python -m pytest \
  tests/test_actions_model_fallback.py \
  tests/test_concurrent_tool_call_isolation.py -q
```

Five targeted reproductions failed before their fixes. The two-file command
above passes 19 tests on the repair commit; nine focused suites passed 125.
Coverage of the production delta is 23/23 executable changed lines and 14/14
branches originating on changed lines; this does not measure all branches in
the surrounding functions. The concurrent test captures worker exceptions and requires every thread to
terminate. These are local protocol checks, not full-repository coverage or
live-provider evidence. Do not bypass model routing in the review workflow.
Protected owner merge, immutable release, consumer adoption, and a real review
replay remain necessary before claiming the review-agent outage is repaired.

## Tool-loop-emitting-agent routing (2026-09-13)

A handoff (above) tells the caller which agent to execute the tool for, but
until this change the *follow-up* carrying that tool's `role: "tool"` result
was not guaranteed to return to the same agent: a virtual selector
(`orchestrator/free`, `orchestrator/auto`, `contextual-orchestrator`) ranks
every request fresh, so a differently-ranked or failed-over provider could
receive tool results for a call it never emitted — an id-format and behavior
mismatch across providers (NIM/OpenRouter/OpenCode), and a real failure mode
for the `noema` and `opencode` reviewers that depend on multi-turn tool use
through this gateway. This closes the Fugu report's (arXiv:2606.21228 §3)
Conductor tool-loop-return contract: `TaskOrchestrator` remembers, in a
bounded `tool_loop_memory` map, which agent served each `tool_call_id`, and
`_apply_tool_loop_route` moves that agent to the front of the
already-fully-filtered candidate order for a follow-up that carries its
result — never overriding an explicit concrete model, and never placing an
otherwise-ineligible agent (circuit open, wrong free/ZDR scope) ahead of the
normal order. Served responses annotate `orchestration.tool_loop_route`
(`"emitting_agent"` or `"fallback"`) and `orchestration.tool_loop_agent_id`
so callers can observe which happened. See
`tests/test_passthrough_provider_failover.py` for the routing, fallback,
explicit-model-precedence, free-model-precedence, and LRU-eviction
contracts.

## References — APA 7th

Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall, P., & Roberts, K. (2024). *Artificial intelligence risk management framework: Generative artificial intelligence profile* (NIST AI 600-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110; STD 97). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110

OpenAI. (n.d.). *Chat completion chunk types* [Source code]. GitHub. Retrieved September 8, 2026, from https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_chunk.py
