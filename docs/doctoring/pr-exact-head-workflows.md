# Pull-request exact-head workflow evidence

## Decision

Contextual Orchestrator's repository-local Tests, Fuzz, and Security workflows must run for pull requests targeting any repository branch, including stacked feature branches, and every checkout in those workflows must select the pull request's exact contributor-head SHA.

The local exact-head checks answer one narrow question: whether the immutable contributor head passes the repository's tests, fuzzing, and security controls. They do not prove that the head integrates cleanly with its target base. Merge-tree compatibility, trusted central coverage, independent review, and branch protection remain separate mandatory evidence surfaces.

## Problem

The inherited workflows filtered `pull_request` events to base branch `main`. Stacked pull requests whose base is another protected integration branch therefore received no local Tests, Fuzz, or Security run. In addition, an `actions/checkout` step without an explicit pull-request head ref uses the event's default ref; GitHub documents `GITHUB_SHA` for `pull_request` as the last merge commit of `refs/pull/<number>/merge`, not the contributor-head commit.

That combination created two evidence gaps:

1. stacked pull requests could have no repository-local validation at all; and
2. runs that did occur could validate GitHub's generated merge commit rather than the exact branch head named by reviews, commit statuses, and dependency receipts.

Synthetic-merge evidence can be useful for integration testing, but it cannot substitute for exact-head evidence when approvals, supply-chain receipts, and cross-repository dependencies are bound to a literal commit SHA.

## Implemented contract

The three local workflows now:

- retain `push` execution only for protected `main`;
- listen to `pull_request` without a base-branch filter so stacked pull requests receive checks;
- set every checkout ref to `${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha }}`;
- keep `persist-credentials: false` on every checkout;
- preserve read-only top-level token permissions;
- preserve the existing same-repository guard for the CodeQL job that needs `security-events: write`; and
- do not add secrets, model credentials, repository writes, branch writers, or `pull_request_target` execution.

`tests/test_pr_exact_head_workflows.py` fails when any of these workflows restores a `main`-only pull-request filter, omits the exact-head ref from a checkout, or persists checkout credentials.

## Trust boundary

The workflow definition continues to use the `pull_request` event, whose fork and Dependabot executions receive GitHub's restricted token and secret treatment. This change does not introduce `pull_request_target`, elevate a pull-request job to a privileged mutation plane, or authorize untrusted branch code to publish approvals or releases.

Executing pull-request-controlled tests always processes untrusted code. Accordingly, repository-local workflows remain isolated from model credentials and release credentials. Their outputs are test and scanner evidence only. A passing local run does not authorize merge, approval, release, central workflow mutation, or downstream acceptance.

## Exact-head and merge-tree evidence are complementary

Local exact-head workflows intentionally test the contributor head itself. A later trusted integration gate must separately materialize or otherwise verify the head against its current base. Neither surface may replace the other:

- exact-head success does not prove base compatibility;
- synthetic-merge success does not prove the literal reviewed head independently passed;
- a cancelled, queued, absent, stale-head, or predecessor-head run proves neither; and
- branch movement invalidates both review and check evidence until the new exact head reruns.

## Test-first lineage

Commit `4de7eee05430a8d7d9b0172ed9a59ee17b3db34d` introduced the permanent regression before the workflow repairs. The inherited workflows still contained `pull_request.branches: [main]` and omitted the required exact-head checkout ref, so the contract was RED by inspection.

Commits `7fa66b449c47423f5c7048afe538c4afad29c4a6` and `e10a1beb87a9ca6b48a2ad8878db513278c10b36` removed the base filter and bound every Tests, Fuzz, and Security checkout to the exact contributor head. A separately materialized networkless run of the focused contract reported three passing cases. Repository GitHub Checks remain authoritative for the complete exact head.

## Failure handling

When an exact-head local workflow fails, inspect that exact run and repair the product or permanent workflow contract test-first. Do not reinterpret a synthetic-merge predecessor run as success.

When a workflow is cancelled after branch movement, treat it as superseded evidence and inspect the new head's run. When the current exact-head run is cancelled without branch movement, rerun the current job only after determining that the cancellation was infrastructure- or operator-caused rather than a hidden product failure.

When a stacked branch cannot run because of repository policy, keep the pull request Draft and correct the policy or workflow through its repository-owned maintenance path. Do not widen credentials or move the job to `pull_request_target` merely to obtain a green check.

## Rollback

Rollback requires reverting the workflow changes and this contract together. A partial rollback that restores a `main`-only pull-request filter or implicit merge-ref checkout recreates an evidence gap and must fail review. Preserve the read-only token boundary, immutable action pins, and non-persisted checkout credentials in every rollback.

## APA 7 references

GitHub. (n.d.). *Events that trigger workflows*. Retrieved August 7, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *Securely using pull_request_target*. Retrieved August 7, 2026, from https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target

GitHub. (n.d.). *Triggering a workflow*. Retrieved August 7, 2026, from https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
