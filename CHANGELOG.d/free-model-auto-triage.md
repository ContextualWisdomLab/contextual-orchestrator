Safety correction: `orchestrator/free` in `mode="auto"` now fails closed to
the conducted workflow without dispatching a triage model. fast-mlsirm 0.11.4
exposes point predictions but no released calibrated decision-uncertainty or
posterior-dominance contract, so even a unique maximum cannot authorize the
lower-assurance direct route. Upstream fast-mlsirm issue #2315 owns the missing
Rust-backed contract, calibration and coverage evidence, immutable release,
and subsequent consumer bump. Explicit caller-selected `mode="route"` remains
unchanged.

Earlier work attempted to triage `orchestrator/free` in `mode="auto"` between
the single-worker route and conduct workflow. That implementation was never
accepted: the free-only call still lacked calibrated decision authority.
Containment now resolves the gateway default, `orchestrator/auto`, and
`orchestrator/free` to conduct before cache lookup, so an unresolved legacy
route entry cannot bypass fail-closed behavior. An explicit `mode="route"`
still forces route.
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
receipt fixtures verify that containment produces task-execution receipts
without an auxiliary triage dispatch.
