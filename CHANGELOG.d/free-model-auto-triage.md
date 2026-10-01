Safety correction: `orchestrator/free` in `mode="auto"` now fails closed to
the conducted workflow without dispatching a triage model. fast-mlsirm 0.11.4
exposes point predictions but no released calibrated decision-uncertainty or
posterior-dominance contract, so even a unique maximum cannot authorize the
lower-assurance direct route. Upstream fast-mlsirm issue #2315 owns the missing
Rust-backed contract, calibration and coverage evidence, immutable release,
and subsequent consumer bump. Explicit caller-selected `mode="route"` remains
unchanged.

Earlier work changed `orchestrator/free` in `mode="auto"` (the default when a
request sends no mode) to triage between the single-worker route and the
conduct workflow, as the default model and `orchestrator/auto` already do. #993 had
pinned the free pool to route, so consumers such as the OpenCode review and
Strix got one worker with failover and never the thinker, worker, verifier
and synthesizer workflow. Both paths stay free-only. `conduct()` and
`route_once()` already select free candidates for this model, and the triage
call is now free-only too. When no free triage agent ranks, it fails closed to
the verified conduct path instead of authorizing route or falling back to a
paid agent. Free auto requests resolve triage before response-cache lookup so
route and conduct answers cannot share an unresolved key. Automatic triage
verdicts are not cached. An explicit `mode="route"` still forces route.
The superseded intermediate implementation required complete, uniquely
identified, finite fast-mlsirm fitted probabilities for every eligible
candidate on the exact prompt. Review proved that these point estimates still
lacked decision uncertainty and could not authorize a route verdict. The
held-out psychometric benchmark
also uses fast-mlsirm's current `detect_dif_logistic_purified` API instead of
its deprecated alias.
The superseded implementation also used canonical system/developer/user
interaction identity, preserved worker-exclusion partitions, and avoided a
stale route-authorizing verdict cache. Those safeguards did not supply the
missing decision-uncertainty contract.
The urllib3 pin is upgraded from 2.7.0 to 2.8.0 in `uv.lock`,
`requirements.lock`, and `requirements-security-ci.txt`, the upstream fixed
release for CVE-2026-97687, CVE-2026-97688, and CVE-2026-97689. Decision
receipt fixtures now provide exact fitted evidence before triage and verify
that automatic triage is recomputed rather than read from a stale verdict
cache.
