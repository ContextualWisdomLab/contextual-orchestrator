# Stacked review dispatch checkpoint — 2026-09-12

## Verified cause and preserved policy

PR #1138 at `3419abf11bc7f67dc4d854b347f1dbe2d1f517dc` first had
Security and Quality run `34687370076` skipped while Draft. Its checked-in
`.github/workflows/security.yml` explicitly excludes Draft PRs from all three
jobs and includes `ready_for_review` among its pull-request events.
After marking the PR ready, run `34687504508` was created for the same head
and was authoritatively queued at this checkpoint. This verifies local event
delivery; Draft filtering is intentional, not a defect candidate. No gate,
ruleset, required approval or model-routing policy was changed.

## Current-head evidence and remaining boundary

PR #1107 at `ff590dce735f6f9378ded1e8ac2160cd1077e4db` has Security and
Quality run `34687545746`, with jobs `103537072059`, `103537071997` and
`103537072142` queued. Earlier `de01e9e1` evidence is historical only.
The queried current-head rollup contained no central Required OpenCode,
Noema or Strix CheckRun entries. This is not success and does not establish
missing credentials, failed event delivery or a central execution failure.
The canonical workflow owner was asked to trace central admission/dispatch;
the consumer must not copy review workflows or weaken branch protections.

Continue observing these existing runs; queued jobs are not restart requests.
Keep local source tests, installed-wheel checks, hosted checks, independent
approval, protected-main adoption and release as separate evidence classes.

Reproduce read-only with `gh pr view 1107 --json headRefOid,statusCheckRollup`
and `gh run view 34687504508 --json headSha,status,conclusion,event`, using
`--repo ContextualWisdomLab/contextual-orchestrator`. Re-fetch heads before
interpreting results; this checkpoint is not a permanently current status.
