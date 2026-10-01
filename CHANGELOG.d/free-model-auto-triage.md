Changed `orchestrator/free` in `mode="auto"` (the default when a request
sends no mode) to triage between the single-worker route and the conduct
workflow, as the default model and `orchestrator/auto` already do. #993 had
pinned the free pool to route, so consumers such as the OpenCode review and
Strix got one worker with failover and never the thinker, worker, verifier
and synthesizer workflow. Both paths stay free-only. `conduct()` and
`route_once()` already select free candidates for this model, and the triage
call is now free-only too. When no free triage agent ranks, it fails closed to
the verified conduct path instead of authorizing route or falling back to a
paid agent. Free auto requests resolve triage before response-cache lookup so
route and conduct answers cannot share an unresolved key. Automatic triage
verdicts are not cached. An explicit `mode="route"` still forces route.
Triage model admission now requires complete, uniquely identified, finite
fast-mlsirm fitted probabilities for every eligible candidate on the exact
prompt. Missing, partial, duplicate, invalid, or tied psychometric evidence
fails closed to conduct; static priority and semantic-neighbor order cannot
authorize a direct-route verdict. The held-out psychometric benchmark
also uses fast-mlsirm's current `detect_dif_logistic_purified` API instead of
its deprecated alias.
Automatic triage now uses the canonical system/developer/user interaction
identity used by judged observations, preserves worker-exclusion partitions,
and recomputes against the current roster and fitted evidence instead of
reusing a stale route-authorizing verdict cache.
The locked urllib3 dependency is upgraded from 2.7.0 to 2.8.0, the upstream
fixed release for CVE-2026-97687, CVE-2026-97688, and CVE-2026-97689.
