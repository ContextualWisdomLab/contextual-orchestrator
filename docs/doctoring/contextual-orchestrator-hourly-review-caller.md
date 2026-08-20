# Contextual Orchestrator hourly review caller

The repository now owns one hourly trigger at minute `07`. It calls the
central protected PR review scheduler with `max_prs=1` and
`max_dispatches=1`, so each run has a bounded mutation scope and then advances
to the next loop on the following hour.

The central scheduler validates the live PR head, dispatches the existing
OpenCode review agent, and selects the contextual-orchestrator gateway after
central PR #1170 and target PR #790 are available on their protected default
branches. This caller does not change the existing review-agent secret scheme
and does not reference `COPILOT_GITHUB_TOKEN`.

`cancel-in-progress: false` is deliberate: a long-running model review must
finish and publish exact-head evidence rather than being discarded by the next
hourly tick. The caller is tested by
`tests/test_hourly_review_scheduler_contract.py`.
