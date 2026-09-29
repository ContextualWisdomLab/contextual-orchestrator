Changed `orchestrator/free` in `mode="auto"` (the default when a request
sends no mode) to triage between the single-worker route and the conduct
workflow, as the default model and `orchestrator/auto` already do. #993 had
pinned the free pool to route, so consumers such as the OpenCode review and
Strix got one worker with failover and never the thinker, worker, verifier
and synthesizer workflow. Both paths stay free-only. `conduct()` and
`route_once()` already select free candidates for this model, and the triage
call is now free-only too. When no free triage agent ranks, it goes straight
to route instead of falling back to a paid agent. The triage cache key
separates free-only verdicts. An explicit `mode="route"` still forces route.
