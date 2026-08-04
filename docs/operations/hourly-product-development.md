# Hourly Product-Development Loop

## Purpose

`Hourly Product Development` converts an empty pull-request queue into one bounded commercial-quality development task. It does not replace the organization-central review and merge system. `ContextualWisdomLab/.github` remains authoritative for reviewing every current head, applying bounded repairs, rerunning required checks, enforcing independent approval, and merging only a policy-clean pull request.

The workflow is intentionally repository-specific because its delegated prompt carries Contextual Orchestrator's architecture, quality, interoperability, research, and NVIDIA NIM evaluation contracts. The PR-maintenance logic remains centralized and is not duplicated here.

## Schedule and single-flight behavior

The workflow runs at minute 47 of every hour and supports a manual `workflow_dispatch` dry run. Its concurrency group is scoped to the repository and uses `cancel-in-progress: false`, so a later schedule cannot cancel a task-dispatch decision already in progress.

The gate evaluates these conditions in order:

1. Read the open pull-request inventory with the built-in read-only `GITHUB_TOKEN`.
2. Stop when any pull request is open, because the central maintenance loop owns that hour.
3. Stop when `COPILOT_GITHUB_TOKEN` is absent.
4. Read every Agent Task page with the dedicated user token.
5. Stop when inventory retrieval fails or the response schema is unexpected.
6. Stop when any task is active or has an unrecognized state.
7. Create exactly one pull-request-producing Agent Task only when all prior gates are clear.

Terminal task states are `completed`, `failed`, `timed_out`, and `cancelled`. Every other value, including a missing state, is treated as active. This fail-closed rule prevents duplicate development tasks when the external API evolves or returns incomplete data.

## Credentials and permissions

The workflow-level GitHub token has only:

- `contents: read`
- `pull-requests: read`

Repository inventory uses that token. Agent Task inventory and creation use the `COPILOT_GITHUB_TOKEN` repository or organization secret because the Agent Tasks API does not accept a GitHub App installation token such as `GITHUB_TOKEN`.

Configure `COPILOT_GITHUB_TOKEN` as a fine-grained user token with Agent tasks read/write access for this repository. Do not add repository-content or pull-request mutation scopes merely to run this workflow. The created cloud task opens a pull request; the scheduled workflow itself does not edit code, push branches, approve reviews, merge, publish, or release.

`NVIDIA_NIM_API_KEY` is not injected into this dispatcher. NVIDIA evaluation work must introduce a separately reviewed benchmark workflow that receives only that secret in the step that contacts NVIDIA, never places the value in argv or artifacts, and follows issue #86's bounded catalog, quality, latency, provenance, and hypothetical-cost contract.

## Delegated product contract

The Agent Task prompt requires one reviewable increment and preserves these repository constraints:

- test-first development;
- complete production statement, branch, and docstring coverage;
- standalone operation plus modular MSA integration;
- compatibility with the organization-central `.github` workflows and naruon;
- descriptive two-word-or-longer `snake_case` database object names;
- current standards, primary documentation, and peer-reviewed evidence for ambiguous behavior;
- Figma or Product Design only when a genuine user interaction needs design work;
- dynamic NVIDIA NIM discovery through `GET /v1/models` when issue #86 is selected;
- actual-free and hypothetical-paid cost accounting as separate measures;
- CHANGELOG and affected documentation updates;
- Semantic Versioning only when the integrated change is release-ready;
- no merge, publication, release, policy bypass, or unrelated refactoring by the delegated task.

## Dry run

A manual run with `dry_run: true` executes all queue, token, and task-inventory gates. When dispatch is permitted, it prints the exact bounded task prompt to the workflow summary but does not call the task-creation endpoint. This mode validates the operational decision without creating a branch or pull request.

A dry run still requires valid Agent Task inventory. Skipping inventory in dry-run mode would allow an operator to receive a misleading `ready` result while another task is active.

## Failure semantics

A missing inventory, unexpected response shape, missing token, open pull request, or active/unknown task produces a non-dispatch reason in the workflow summary. These states are safe no-ops, not successful evidence that development occurred.

A task-creation API failure fails the job. It is not converted into a successful no-op because the gate had already established that a task should be created; operational failure at that point needs visible intervention rather than silent loss.

## Operational verification

For a proposed workflow change, run:

```bash
python -m pytest -q tests/test_hourly_product_development_workflow.py
python -m pytest -q
```

Then require the current pull-request head to pass repository Tests, Fuzz, Security, Security Scan, SAST, central OpenCode review, CodeRabbit where configured, and every branch-protection check. The workflow is active only after it is merged into the default branch.

## Disabling the loop

Disable the scheduled workflow in GitHub Actions or remove only the `schedule` trigger through a reviewed pull request. Do not weaken the queue, inventory, credential, or independent-review gates as a shortcut. Manual dry runs may remain available while scheduled dispatch is disabled.
