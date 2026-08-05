# Pull-request exact-head verification boundary

## Decision

Repository-local Tests, Fuzz, and Security jobs explicitly check out
`github.event.pull_request.head.sha` for `pull_request` events. Push, schedule,
and manual runs continue to use `github.sha`. Checkout credentials remain
non-persistent.

GitHub documents that an open, mergeable pull request ordinarily sets
`GITHUB_REF` to `refs/pull/<number>/merge` and `GITHUB_SHA` to the synthetic
merge commit. The official `actions/checkout` documentation therefore gives an
explicit `ref: ${{ github.event.pull_request.head.sha }}` example for checking
the contributor head instead of that merge commit.

This repository needs both evidence classes, but it must not confuse them:

- **Exact-head evidence** proves the immutable contributor SHA that review and
  approval refer to.
- **Integration evidence** proves a clearly identified merge result against a
  clearly identified base.

A successful workflow associated with a branch SHA is not automatically
exact-head evidence. The checked-out commit in the job log is authoritative.
Queued, pending, cancelled, predecessor-head, stale-base, or synthetic-merge
results cannot be relabeled as current-head success.

## Threat and permission boundary

These workflows use the `pull_request` event, read-only repository permissions,
and no provider or deployment secret. Selecting the pull-request head therefore
does not convert a privileged `pull_request_target` or secret-bearing workflow
into an untrusted-code execution path. The explicit ref is intentionally limited
to the repository-local verification workflows covered by the regression
contract.

Organization-central workflows retain their own authority and threat model.
Their results must be classified from their actual checkout behavior. A central
workflow that intentionally evaluates a merge commit remains useful integration
evidence, but it does not satisfy an exact-head gate unless it separately proves
the contributor SHA under its documented policy.

## Regression contract

`tests/test_pr_exact_head_workflows.py` counts every `actions/checkout` use in:

- `.github/workflows/tests.yml`
- `.github/workflows/fuzz.yml`
- `.github/workflows/security.yml`

For every checkout, the test requires the event-aware exact-head expression and
`persist-credentials: false`. Adding another checkout without the same boundary
fails the full unit and contract suite.

## References

GitHub. (2026). *Events that trigger workflows: How the merge branch affects
your workflow*. GitHub Docs.
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (2026). *Checkout pull request HEAD commit instead of merge commit*.
In *actions/checkout*. GitHub.
https://github.com/actions/checkout#checkout-pull-request-head-commit-instead-of-merge-commit
