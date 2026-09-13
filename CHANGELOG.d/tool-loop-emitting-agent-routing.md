# Tool-loop-emitting-agent routing

Closed a paper-fidelity gap (Fugu report arXiv:2606.21228 §3; Fugu-Ultra
Conductor): the paper's Conductor routes a tool loop back to the agent that
emitted the tool call, but a follow-up `POST /v1/chat/completions` carrying
`role: "tool"` results for a prior `tool_calls` batch was previously ranked
like any new request under a virtual selector (`orchestrator/free`,
`orchestrator/auto`, `contextual-orchestrator`), so a different provider or
model could receive tool results for calls it never emitted.

`TaskOrchestrator` now keeps a bounded, thread-safe `tool_loop_memory` map
(`tool_call_id -> emitting agent id`, default bound
`TOOL_LOOP_MEMORY_MAX_ENTRIES = 512`, configurable via the new
`tool_loop_memory_max_entries` constructor argument) recorded whenever a
served response carries `tool_calls` on `proxy_completion`'s single-agent
passthrough, `route_once`, and `conduct`'s worker step. A follow-up whose
`role: "tool"` messages reference a remembered `tool_call_id` moves that
agent to the front of the already-fully-filtered candidate order — but only
when it is still eligible under the request's own constraints (explicit
concrete model, free/ZDR scope, circuit-breaker state); an ineligible
remembered agent falls back to the normal order instead. Served responses
now carry `orchestration.tool_loop_route` (`"emitting_agent"` or
`"fallback"`) and `orchestration.tool_loop_agent_id` as routing evidence.

The Responses API's structured-synthesis path
(`_orchestrated_provider_completion`) is not yet wired into this map; it
remains a follow-up.
