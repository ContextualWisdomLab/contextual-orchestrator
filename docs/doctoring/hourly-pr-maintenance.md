# Hourly PR Maintenance Control Boundary

## Decision

Contextual Orchestrator owns a small scheduled caller while the organization
`.github` repository owns the reusable review-repair policy and the OpenCode
writer. The caller sends a `repository_dispatch` event to the protected central
control plane every hour; it does not copy the repair engine into the product
repository.

## Cadence and bounded work

The heartbeat runs at minute 11 of every hour. It asks the central scheduler to
inspect up to 100 open `main` pull requests, dispatch at most one repair, and
enforce a one-hour same-head retry floor. Non-cancelling concurrency avoids
terminating legitimate work merely because the next heartbeat arrived.

The central scheduler performs root-cause analysis and remediation feasibility
screening. Queued checks, reviewer latency, missing independent approval,
provider delay, billing limits, and unavailable credentials are operational
states rather than evidence of a source defect. They must not produce invented
commits.

## Credential, model, and authority boundaries

The caller uses only the established `PR_REVIEW_MERGE_TOKEN`, falling back to
`OPENCODE_APPROVE_TOKEN`, to create the central dispatch event. Its generated
`GITHUB_TOKEN` remains read-only. The caller receives neither
`NVIDIA_NIM_API_KEY` nor any model prompt or source archive. The central,
separately reviewed OpenCode worker owns NVIDIA NIM access and repair execution.
`COPILOT_GITHUB_TOKEN` is not a model, scheduler, review, or merge credential in
this path.

A repair cannot approve itself, weaken checks, label pending evidence as
passing, replay an ambiguous state-changing tool call, or bypass independent non-author approval. Exact-head CI, security review, coverage, docstrings, and
branch protection remain authoritative.

## Standalone and ecosystem behavior

The product remains independently deployable. The dispatch payload contains
only repository identity, protected base, queue bounds, and retry cadence.
Central `.github` may improve the repair engine without importing product code;
Contextual Orchestrator continues to own provider routing, tool execution,
credential authority, audit behavior, and release evidence.

## Failure handling and rollback

Missing dispatch credentials and non-204 GitHub responses fail closed with an
actionable error. Permanent tests bind the cron, single-flight policy,
one-dispatch limit, one-hour retry floor, exact target, read-only caller
permission, explicit credentials, and absence of model or Copilot secrets.
Rollback removes the caller, test, and this record; it does not change reviewer
identities, central worker secrets, branch protection, or product runtime
behavior.

## APA 7th references

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 15, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub, Inc. (n.d.-b). *REST API endpoints for repositories: Create a repository
dispatch event*. GitHub Docs. Retrieved August 15, 2026, from
https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event

GitHub, Inc. (n.d.-c). *Workflow syntax for GitHub Actions: Permissions*.
GitHub Docs. Retrieved August 15, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions
