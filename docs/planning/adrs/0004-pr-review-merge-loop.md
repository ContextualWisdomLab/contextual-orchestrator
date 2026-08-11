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
    target: "every named required check-run passes on the exact PR head SHA before merge; local commands are supplementary"
    measurement_window: "each PR lifecycle"
    source: "GitHub Actions checks and local reproducible commands"
  - metric: "review remediation"
    target: "every actionable security or correctness comment is fixed and revalidated; only non-blocking risk may be explicitly accepted before merge"
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

### Exact merge-gate contract

The required check-run names are read from each protected `main` branch and must be
green on one recorded `verified_head_sha` immediately before merge. For
`contextual-orchestrator`, the required contexts are `Hypothesis property tests`,
`Atheris coverage-guided`, `CodeQL analysis`, `Python supply chain`,
`dependency-review`, `osv-scan`, `trivy-fs`, `scorecard`, `coverage-evidence`,
`opencode-review`, `strix`, and `scan-pr-queue`. For `fast-mlsirm`, they are
`Analyze (actions)`, `close-empty`, `scan-pr-queue`, `dependency-review`,
`osv-scan`, `trivy-fs`, `scorecard`, `strix`, `required-workflow-bootstrap`,
`coverage-evidence`, `opencode-review`, `python`, `rust`, `package`, and `fuzz`.
The repository-local job names are defined in `.github/workflows/`; central
contexts remain required even when their workflow file is outside the repository.
Local pytest, Ruff, package, and fuzz commands are reproducible supporting
evidence only; they never replace a required GitHub check-run.

The maintainer records the PR head SHA and the SHA attached to every required
check-run. If the PR head, any check SHA, or the reviewed diff changes, the merge
stops and the complete gate is re-evaluated on the new head. A documentation-only
note cannot resolve an actionable security or correctness finding; it remains a
merge blocker until code/test remediation and revalidation are complete. A
non-blocking risk may be accepted only with an owner, rationale, tracking issue,
and expiry date.

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
| Review feedback may reveal new quality/security problems. | Apply every actionable comment, extend Goal/ADR, rerun tests, and repeat; documentation alone never clears a security/correctness blocker. | Required for completion |
| A stale green commit can be merged accidentally. | Check exact PR head and merge only that SHA. | Required for completion |
| Required contexts can drift between local workflow files and protected-branch rules. | Read the protected-branch context list, record each check SHA, and treat local commands as supplementary. | Required for completion |
| CLI key-only split-token mode can silently select the single-token path. | Treat explicit `--admin-token-key`/`--inference-token-key` as split-mode selectors and test KV resolution before startup. | Required for completion |
| Partial split-token CLI errors can omit the supported KV-key flags and mislead operators about the accepted credential forms. | Name both explicit token and `--admin-token-key`/`--inference-token-key` paths in the validation error and regression-test the message. | Implemented in current head |
| DNS can change between provider validation and connection. | Return the validated sockaddr and connect directly to it while preserving hostname-based TLS SNI and Host semantics. | Required for completion |
| Model-judge output can contain wrappers, extra fields, duplicate keys, or parser-stressing input. | Require one bounded duplicate-free JSON object with exactly `decision` and `reason`; fail closed and cover Hypothesis/Atheris paths. | Required for completion |
| Container startup can expose a bearer secret through env/argv instead of the KV boundary. | Pass a credential name (`--auth-token-key`) and keep secret material in the Keyverse/KV adapter. | Required for completion |
| External Keyverse/OIDC verification can be marked unavailable by sales readiness. | Treat the explicit external bearer verifier mode as authenticated while preserving fail-closed scope checks. | Required for completion |
| Self-approval may be disallowed or misleading. | Never fabricate approval; use authorized review or leave the PR unmerged with an explicit reason. | Required for completion |
| Two repositories can drift. | Use linked PRs/commits and run contextual + fast-mlsirm tests before each merge. | Required for completion |
| Secrets can leak through PR logs or ADRs. | Run secret scans, redact outputs, and keep Keyverse/KV credentials outside commits. | Required for completion |
| Central Strix can fail before producing a report when its external model provider is rate-limited or unavailable (observed NVIDIA NIM 429 and GitHub Models 410 brownout). | Keep the security gate fail-closed; record the provider/model error, retry the same verified HEAD after provider recovery, and never treat missing reports as a clean scan. | Required for completion |
| The two repositories' central Strix gate versions classified the same provider outage differently: `fast-mlsirm` reported a neutral pass without a structured report while `contextual-orchestrator` failed closed. | Align the trusted gate contract across repositories; until it is aligned, treat every neutral/no-report result as a blocking failure and merge only after a structured report proves the scan completed. This ADR defines no security-owner override for missing evidence; retry the same verified HEAD after provider recovery. | Required follow-up |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| CI passes before a later force-push. | low | high | Re-check exact head immediately before merge. | maintainer |
| Review loop churns without convergence. | medium | medium | Keep each iteration scoped to evidence, add a regression test, and stop only at a concrete acceptance gate. | maintainer |
| Merge permission is unavailable. | medium | medium | Continue local/remote checks, preserve the PR, and report the exact permission state; do not bypass protection. | repository admin |
| Security-provider outage delays a required scan. | medium | high | Preserve the failed evidence, do not weaken the gate, and rerun the exact HEAD when an authorized provider is available. | CI owner |
| Gate-version drift creates inconsistent no-report semantics across linked PRs. | medium | high | Pin/upgrade the shared trusted gate together, require structured-report evidence for both repositories, and keep the discrepancy visible in the PR/ADR. | CI owner |

## Rollback / Exit Strategy

If a merged change regresses, revert the merge commit through a new reviewed PR and keep the original ADR lineage. If merge is blocked, leave the verified PR open and record the external permission/check condition; do not delete work or weaken the gate.

## Affected Components

* contextual-orchestrator branch, PR, CI, and merge state
* fast-mlsirm branch, PR, CI, and merge state
* .github/workflows/
* docs/planning/adrs/

## More Information

This ADR is the operational extension of the active Goal: implementation, evidence, review remediation, and merge are all part of completion. The Goal is dynamically expanded whenever a new review or test finding changes the acceptance boundary.
