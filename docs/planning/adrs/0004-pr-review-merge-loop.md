---
id: "0004"
title: "Auditable PR review, remediation, and merge loop"
status: accepted
proposed_date: "2026-08-11"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "repository CI workflows"
  - "repository security policy"
informed:
  - "contributors"
affected_components:
  - ".github/workflows/tests.yml"
  - ".github/workflows/security.yml"
  - "repository branches and pull requests"
  - "docs/planning/adrs/"
effort: M
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0003-keyverse-authentication-boundary.md"
    relation: informational
  - path: "AGENTS.md"
    relation: informational
asr_triggers:
  - kind: maintainability
    evidence: "Changes span two repositories and require repeated review/test feedback."
    note: "The loop makes each remediation and verification result traceable."
  - kind: security
    evidence: "Merge must not bypass required checks, current-head review, or secret boundaries."
    note: "No credential or branch protection bypass is part of the loop."
success_criteria:
  - metric: "PR verification"
    target: "all required checks pass on the exact head commit before merge"
    measurement_window: "each PR lifecycle"
    source: "GitHub Actions checks and local reproducible commands"
  - metric: "review remediation"
    target: "every actionable review comment is resolved or explicitly documented before merge"
    measurement_window: "each review iteration"
    source: "PR conversation, diff, and follow-up commit history"
---

# Auditable PR review, remediation, and merge loop

## Context

The requested work changes a gateway and its evaluation companion, so a local green test run is not enough. The change must survive a current-head review, CI/security checks, and a merge decision that does not bypass repository protections. If a review finds a new issue, the Goal expands and the issue is recorded in an ADR before the next iteration.

> .github/workflows/tests.yml runs the full unit and contract suite on pull requests targeting main.
>
> Repository instructions require security checks and prohibit leaking authentication tokens or provider secrets.
>
> This task explicitly requires PR creation, review-response iteration, and Merge rather than stopping at a local patch.

## Decision Drivers

* Make the final state reproducible and reviewable from commits, checks, and ADRs.
* Continue through actionable review findings instead of treating the first PR as final.
* Merge only the exact tested head and never bypass branch protection or unresolved security concerns.
* Keep the same discipline for contextual-orchestrator and fast-mlsirm.

## Considered Options

* Apply local edits and stop after local tests.
* Open one PR and merge immediately after the first green local run.
* Use a repeatable branch → test → PR → review → remediate → re-test → exact-head merge loop.

## Decision Outcome

Chosen option: "Repeatable exact-head review and merge loop".

| Driver | Stop after local tests | Immediate merge | Exact-head review loop |
| --- | --- | --- | --- |
| Review quality | unknown | shallow | actionable findings iterated |
| CI/security evidence | absent | partial | required checks observed |
| Traceability | working tree only | one commit | ADR + commits + PR conversation |
| Safety | easy to miss regressions | protection pressure | merge only after evidence |

The maintainer creates a codex/ branch, commits coherent changes, pushes a PR, inspects the diff and current checks, records/replies to actionable review findings, applies fixes, reruns tests and checks, and merges only when the PR head is the verified commit. If the platform disallows self-approval, the maintainer must not fake approval; it waits for or requests an authorized reviewer while continuing all safe local verification.

### Consequences

* Good, because every new concern becomes a reviewable code/test/ADR item.
* Good, because merge is tied to exact-head checks rather than an earlier green commit.
* Good, because user-requested autonomy is bounded by repository protection and secret safety.
* Bad, because the workflow takes longer and may require an external authorized reviewer.
* Bad, because GitHub permissions, branch protection, or CI availability can prevent autonomous merge; the evidence and remediation work still remain useful.

### Confirmation

For each repository, record branch, commit, PR URL, review result, check result, remediation commits, and merge SHA. Re-open the merged diff and rerun the smallest relevant local tests after merge. Do not report Merge unless the platform confirms it.

## Pros and Cons of the Options

### Stop after local tests

* Good, because it is fast.
* Bad, because no remote CI, review, or merge evidence exists.

### Immediate merge

* Good, because it reduces elapsed time.
* Bad, because it discards the requested review iteration and can merge an unreviewed defect.
* Bad, because it encourages bypassing protections.

### Exact-head review loop (chosen)

* Good, because it handles review findings until the current head is green.
* Good, because it preserves a clear audit trail.
* Bad, because external reviewer/CI state remains outside the local process.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Local tests alone cannot validate PR integration. | Push a PR and observe required CI/security checks. | Required for completion |
| Review feedback may reveal new quality/security problems. | Apply every actionable comment, extend Goal/ADR, rerun tests, and repeat. | Required for completion |
| A stale green commit can be merged accidentally. | Check exact PR head and merge only that SHA. | Required for completion |
| Self-approval may be disallowed or misleading. | Never fabricate approval; use authorized review or leave the PR unmerged with an explicit reason. | Required for completion |
| Two repositories can drift. | Use linked PRs/commits and run contextual + fast-mlsirm tests before each merge. | Required for completion |
| Secrets can leak through PR logs or ADRs. | Run secret scans, redact outputs, and keep Keyverse/KV credentials outside commits. | Required for completion |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| CI passes before a later force-push. | low | high | Re-check exact head immediately before merge. | maintainer |
| Review loop churns without convergence. | medium | medium | Keep each iteration scoped to evidence, add a regression test, and stop only at a concrete acceptance gate. | maintainer |
| Merge permission is unavailable. | medium | medium | Continue local/remote checks, preserve the PR, and report the exact permission state; do not bypass protection. | repository admin |

## Rollback / Exit Strategy

If a merged change regresses, revert the merge commit through a new reviewed PR and keep the original ADR lineage. If merge is blocked, leave the verified PR open and record the external permission/check condition; do not delete work or weaken the gate.

## Affected Components

* contextual-orchestrator branch, PR, CI, and merge state
* fast-mlsirm branch, PR, CI, and merge state
* .github/workflows/
* docs/planning/adrs/

## More Information

This ADR is the operational extension of the active Goal: implementation, evidence, review remediation, and merge are all part of completion. The Goal is dynamically expanded whenever a new review or test finding changes the acceptance boundary.
