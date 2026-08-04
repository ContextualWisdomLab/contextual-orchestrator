# Hourly Product-Development Loop

## Purpose

`Hourly Product Development` converts an empty pull-request queue into one bounded commercial-quality development increment produced by an OpenCode agent session against NVIDIA NIM. It does not replace the organization-central review and merge system. `ContextualWisdomLab/.github` remains authoritative for reviewing every current head, applying bounded repairs, rerunning required checks, enforcing independent approval, and merging only a policy-clean pull request.

The workflow is intentionally repository-specific because its delegated prompt carries Contextual Orchestrator's architecture, quality, interoperability, research, and NVIDIA NIM evaluation contracts. The PR-maintenance logic remains centralized and is not duplicated here.

## Schedule and single-flight behavior

The workflow runs at minute 47 of every hour and supports a manual `workflow_dispatch` dry run. Its concurrency group is scoped to the repository and uses `cancel-in-progress: false`, so a later schedule cannot cancel an agent session already in progress; queued runs wait and then re-evaluate the gate.

The gate evaluates these conditions in order:

1. Read the open pull-request inventory with the built-in read-only `GITHUB_TOKEN`; stop when it is unavailable.
2. Stop when any pull request is open, because the central maintenance loop owns that hour.
3. Stop when `NVIDIA_NIM_API_KEY` is absent.
4. Run exactly one bounded agent session in a read-only GitHub job.
5. Package any candidate as a bounded patch artifact.
6. On a fresh runner with no NVIDIA secret, validate the artifact and open exactly one pull request.

Because the agent runs synchronously inside the gated job, the concurrency group is the task inventory: there is no external Agent Task queue to poll, and a finished run leaves either nothing or an open pull request that closes the gate for the next hour.

## Credentials, permissions, and trust boundary

The workflow uses two separate jobs and runners.

### Model-bearing development job

The `develop-product-gap` job has only:

- `contents: read`;
- `pull-requests: read`.

The OpenCode session authenticates to NVIDIA NIM with the `NVIDIA_NIM_API_KEY` organization secret, bound to `NVIDIA_API_KEY` only for the model-execution step. The agent process runs without `GH_TOKEN`, `GITHUB_TOKEN`, the repository inventory token, OIDC request variables, or GitHub command-file variables. The checkout uses `persist-credentials: false`.

The agent cannot push a branch or open a pull request. Its output is reduced to a patch and small JSON metadata artifact. That artifact is treated as untrusted and retained for one day.

### Trusted publication job

The `publish-product-gap` job runs on a fresh runner and receives no NVIDIA credential. It has the minimum write permissions needed to publish the proposal:

- `actions: read` to download the current run's candidate artifact;
- `contents: write` to push one generated branch;
- `pull-requests: write` to open one pull request.

Before applying the patch, the job enforces a 5 MiB and 200-file boundary, validates UTF-8 metadata, rejects path traversal and Git-internal paths, rejects symbolic-link and submodule modes, rejects `.gitmodules`, `opencode.json`, and `PR_MESSAGE.md`, and runs `git apply --check`. The patch is then applied in a fresh checkout with an empty `core.hooksPath`; commit and push commands retain the same trusted hook boundary. This prevents an agent-controlled Git configuration, hook, executable, or working directory from crossing into the credentialed publication runner.

No Copilot subscription, Agent Tasks API access, or fine-grained user token is involved.

The dispatcher exposes `NVIDIA_NIM_API_KEY` only as the agent's reasoning backend. NVIDIA evaluation work for the product itself must still introduce a separately reviewed benchmark workflow that receives the secret only in the step that contacts NVIDIA, never places the value in argv or artifacts, and follows issue #86's bounded catalog, quality, latency, provenance, and hypothetical-cost contract.

## Delegated product contract

The agent prompt requires one reviewable increment and preserves these repository constraints:

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

A manual run with `dry_run: true` executes the queue and credential gates. When dispatch is permitted, it prints the exact bounded agent prompt to the workflow summary but does not start the agent session, upload an artifact, create a branch, or open a pull request.

## Failure semantics

A missing pull-request inventory, missing NIM secret, or open pull request produces a non-dispatch reason in the workflow summary. These states are safe no-ops, not successful evidence that development occurred.

When every NVIDIA NIM model candidate fails, the development job discards partial work and fails. An agent session that completes without changing the tree is reported as a no-op. An oversized, malformed, ambiguous, path-unsafe, symlink-bearing, submodule-bearing, or otherwise invalid candidate fails closed before the publication token is used.

## Operational verification

For a proposed workflow change, run:

```bash
python -m pytest -q tests/test_hourly_product_development_workflow.py
python -m pytest -q
```

Then require the current pull-request head to pass repository Tests, Fuzz, Security, Security Scan, SAST, central OpenCode review, CodeRabbit where configured, and every branch-protection check. The workflow is active only after it is merged into the default branch.

## Disabling the loop

Disable the scheduled workflow in GitHub Actions or remove only the `schedule` trigger through a reviewed pull request. Do not weaken the queue, credential, artifact-validation, fresh-runner, or independent-review gates as a shortcut. Manual dry runs may remain available while scheduled dispatch is disabled.
