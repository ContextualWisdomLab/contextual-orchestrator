# Contextual Orchestrator hourly review caller

The repository owns one hourly trigger at minute `07`. It calls the central
protected PR review scheduler with `max_prs=1` and `max_dispatches=1`, so each
run has a bounded mutation scope and the next hour advances the loop.

The central scheduler validates the live PR head, dispatches the existing
OpenCode review agent, and selects the contextual-orchestrator gateway after
central PR #1170 and target PR #790 are available on their protected default
branches. This caller forwards only the two established scheduler secrets by
name, does not inherit the caller secret set, and does not reference
`COPILOT_GITHUB_TOKEN`.

`cancel-in-progress: false` is deliberate: a long-running model review must
finish and publish exact-head evidence rather than being discarded by the next
hourly tick. The caller is tested by
`tests/test_hourly_review_scheduler_contract.py`.

## Evidence boundary

At authoring time, central PR #1170 was open at exact head
`4684f6e212ba40d12e5217f0f52ee1e90c796ed8` and target PR #790 was pinned at
`0071751782ae535721e71785c3037989d2d27b77`. These are integration
prerequisites, not evidence that the caller has already run in production.
