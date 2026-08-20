# ADR 0028: Schedule the Protected Hourly Review Loop

- Status: Accepted
- Date: 2026-08-21
- Decision owners: contextual-orchestrator maintainers

## Decision

Run one repository caller at minute 07 of every hour. The caller invokes the
central `.github` `pr-review-fix-scheduler.yml` reusable workflow for exactly
one eligible PR or buyer-visible product-gap iteration, with one dispatch and a
one-hour redispatch window. It passes the target repository and `main` base
explicitly, forwards only `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN`, and never uses `secrets: inherit` or
`COPILOT_GITHUB_TOKEN`.

The caller does not cancel an in-flight run. A long OpenCode, Noema, or Strix
review therefore survives the next hourly tick. The central scheduler remains
the authority for current-head validation, review-agent identity, Checks,
protected merge, and the contextual-orchestrator gateway introduced by central
PR #1183 and target PR #790.

## Consequences

- An empty PR queue still produces a bounded product-gap iteration through the
  central scheduler's existing fallback contract.
- The repository remains independently runnable; the caller is only an
  orchestration connector.
- The reusable workflow must be present on central `main` before the scheduled
  caller can dispatch successfully.

## Customer next action

After this PR and central PR #1183 are merged, enable Actions for this
repository. The first scheduled run will inspect one current PR at `07` past
the next hour. Use the normal protected scheduler path for subsequent runs;
this caller intentionally has no manual branch-selection entry point.

## References (APA 7)

GitHub. (n.d.). *Events that trigger workflows*. Retrieved August 21, 2026,
from https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows

GitHub. (n.d.). *Reusing workflows*. Retrieved August 21, 2026, from
https://docs.github.com/en/actions/sharing-automations/reusing-workflows
