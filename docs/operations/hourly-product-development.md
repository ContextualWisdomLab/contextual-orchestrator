# Hourly Product-Development Loop

## Purpose

`Hourly Product Development` converts an empty pull-request queue into one bounded commercial-quality development increment produced by an in-workflow OpenCode agent session against NVIDIA NIM. It does not replace the organization-central review and merge system. `ContextualWisdomLab/.github` remains authoritative for reviewing every current head, applying bounded repairs, rerunning required checks, enforcing independent approval, and merging only a policy-clean pull request.

The workflow is intentionally repository-specific because its delegated prompt carries Contextual Orchestrator's architecture, quality, interoperability, research, and NVIDIA NIM evaluation contracts. The PR-maintenance logic remains centralized and is not duplicated here.

## Schedule and single-flight behavior

The workflow runs at minute 47 of every hour and supports a manual `workflow_dispatch` dry run. Its concurrency group is scoped to the repository and uses `cancel-in-progress: false`, so a later schedule cannot cancel an agent session already in progress; queued runs wait and then re-evaluate the gate.

The gate evaluates these conditions in order:

1. Read the open pull-request inventory with the built-in `GITHUB_TOKEN`; stop when it is unavailable.
2. Stop when any pull request is open, because the central maintenance loop owns that hour.
3. Stop when `NVIDIA_NIM_API_KEY` is absent.
4. Run exactly one bounded agent session, then package any working-tree changes as exactly one pull request.

Because the agent runs synchronously inside the gated job, the concurrency group is the task inventory: there is no external Agent Task queue to poll, and a finished run leaves either nothing or an open pull request that closes the gate for the next hour.

## Credentials and permissions

The workflow-level GitHub token has:

- `contents: write` — used only to push the agent's `nim-agent/product-dev-*` branch;
- `pull-requests: write` — used only to open the bounded pull request.

The OpenCode agent session authenticates to NVIDIA NIM with the `NVIDIA_NIM_API_KEY` organization secret, bound to `NVIDIA_API_KEY` for the pinned, SHA256-verified OpenCode CLI. The agent process runs with `GH_TOKEN`, `GITHUB_TOKEN`, and the OIDC request environment stripped, and the checkout uses `persist-credentials: false`, so the model never holds a GitHub credential. No Copilot subscription, Agent Tasks API access, or fine-grained user token is involved.

The dispatcher exposes `NVIDIA_NIM_API_KEY` only as the agent's own reasoning backend. NVIDIA evaluation work for the product itself must still introduce a separately reviewed benchmark workflow that receives the secret only in the step that contacts NVIDIA, never places the value in argv or artifacts, and follows issue #86's bounded catalog, quality, latency, provenance, and hypothetical-cost contract.

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

A manual run with `dry_run: true` executes the queue and credential gates. When dispatch is permitted, it prints the exact bounded agent prompt to the workflow summary but does not start the agent session. This mode validates the operational decision without creating a branch or pull request.

## Failure semantics

A missing pull-request inventory, missing NIM secret, or open pull request produces a non-dispatch reason in the workflow summary. These states are safe no-ops, not successful evidence that development occurred.

When every NVIDIA NIM model candidate fails, the run discards partial work and fails the job. It is not converted into a successful no-op because the gate had already established that a session should run; operational failure at that point needs visible intervention rather than silent loss. An agent session that completes without changing the tree is reported as a no-op.

## Operational verification

For a proposed workflow change, run:

```bash
python -m pytest -q tests/test_hourly_product_development_workflow.py
python -m pytest -q
```

Then require the current pull-request head to pass repository Tests, Fuzz, Security, Security Scan, SAST, central OpenCode review, CodeRabbit where configured, and every branch-protection check. The workflow is active only after it is merged into the default branch.

## Disabling the loop

Disable the scheduled workflow in GitHub Actions or remove only the `schedule` trigger through a reviewed pull request. Do not weaken the queue, inventory, credential, or independent-review gates as a shortcut. Manual dry runs may remain available while scheduled dispatch is disabled.
