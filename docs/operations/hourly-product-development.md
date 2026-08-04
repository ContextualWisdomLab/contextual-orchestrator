# Hourly Product-Development Loop

## Purpose

`Hourly Product Development` converts an empty pull-request queue into one bounded commercial-quality development increment produced by an OpenCode agent against NVIDIA NIM. It does not replace the organization-central review and merge system. `ContextualWisdomLab/.github` remains authoritative for reviewing every current head, applying bounded repairs, rerunning required checks, enforcing independent approval, and merging only a policy-clean pull request.

The workflow is repository-specific because its delegated prompt carries Contextual Orchestrator's architecture, quality, interoperability, research, and NVIDIA evaluation contracts. PR-maintenance logic remains centralized and is not duplicated here.

## Schedule and single-flight behavior

The workflow runs at minute 47 of every hour and supports a manual `workflow_dispatch` dry run. Its concurrency group is scoped to the repository and uses `cancel-in-progress: false`, so a later schedule cannot cancel an agent session already in progress; queued runs wait and then re-evaluate the gate.

The gate evaluates these conditions in order:

1. Read the open pull-request inventory with the built-in read-only `GITHUB_TOKEN`; stop when it is unavailable.
2. Stop when any pull request is open, because the central maintenance loop owns that hour.
3. Stop when `NVIDIA_NIM_API_KEY` is absent.
4. Run exactly one bounded agent session in a credential-free, network-isolated container.
5. Validate the candidate filesystem and package it as a bounded patch artifact.
6. On a fresh runner with no NVIDIA credential, validate the artifact and open exactly one pull request.

Because the agent runs synchronously inside the gated job, the concurrency group is the task inventory: there is no external Agent Task queue to poll, and a finished run leaves either nothing or an open pull request that closes the gate for the next hour.

## Why a credential broker is required

OpenCode's official security documentation states that its permission prompts are not a security sandbox. An agent with the Bash tool inherits the host process's filesystem, process, environment, and network authority. Therefore the NVIDIA secret must not be placed in the OpenCode process environment even when GitHub tokens have already been removed.

The workflow uses two containers and two Docker networks:

- an **agent container** attached only to an internal network;
- a **credential broker** attached to that internal network and a separate egress network.

The agent can reach only the broker. It receives neither `NVIDIA_NIM_API_KEY` nor a GitHub/OIDC token, has no Docker socket, and cannot route directly to the Internet. The broker receives the NIM key but has no repository mount, GitHub credential, agent tools, or publication permission.

## Model-bearing development job

The `develop-product-gap` job has only:

- `contents: read`;
- `pull-requests: read`.

### Agent container

The agent image is built from the repository's digest-pinned Python base and the SHA-256-verified OpenCode binary. Its Python test dependencies come from the existing hash-locked property-test requirements.

The container runs with:

- the internal Docker network only;
- a read-only root filesystem;
- writable size-bounded tmpfs mounts for `/tmp` and the agent home;
- all Linux capabilities dropped;
- `no-new-privileges`;
- PID, memory, CPU, and execution-time limits;
- the checkout mounted read/write but `.git` over-mounted read-only;
- no Docker socket;
- no GitHub token, OIDC token, NVIDIA key, or GitHub command-file mount;
- project OpenCode configuration and Claude compatibility disabled;
- an explicit read-only OpenCode configuration mounted from trusted workflow code.

OpenCode points to `http://nim-proxy:8001/v1` with a non-secret placeholder key. Tool permissions also deny push, commit, GitHub CLI, Docker, web-fetch, and external-directory operations. These permissions are defense in depth only; the container and network boundaries are the security controls.

### NVIDIA credential broker

The broker is a stdlib-only Python process running as an unprivileged numeric user in a separate read-only container. It has all Linux capabilities dropped, `no-new-privileges`, bounded PID/memory/CPU resources, no host port, no repository mount, and suppressed request logging.

It enforces:

- the fixed TLS-verified upstream host `integrate.api.nvidia.com`;
- only `GET /v1/models` and `POST /v1/chat/completions`;
- no query targets, absolute URLs, redirects, environment proxies, or caller-supplied authorization;
- a maximum of 128 requests;
- at most two concurrent upstream calls;
- a 2 MiB request body limit;
- a 32 MiB response limit;
- JSON-object validation for chat requests;
- response content types limited to JSON and server-sent events;
- generic, secret-free error responses.

The broker strips the agent's placeholder authorization and injects the real NIM key only into the fixed upstream HTTPS request. It never returns upstream authorization, cookies, redirect locations, or arbitrary headers to the agent.

## Candidate filesystem boundary

After the agent exits, trusted host code scans the checkout without following links. The candidate fails closed when it contains:

- symbolic links, sockets, FIFOs, devices, or other non-regular entries;
- more than 20,000 filesystem entries;
- more than 256 MiB of regular-file content;
- a nested `.git` entry.

The remaining candidate is reduced to a binary Git patch no larger than 5 MiB plus UTF-8 PR metadata no larger than 64 KiB. No container, cache, model response, provider credential, prompt log, or arbitrary agent artifact is published.

## Trusted publication job

The `publish-product-gap` job runs on a fresh runner and receives no NVIDIA credential. It has the minimum write permissions needed to publish the proposal:

- `actions: read` to download the current run's candidate artifact;
- `contents: write` to push one generated branch;
- `pull-requests: write` to open one pull request.

Before applying the patch, the job enforces the artifact size and file-count boundaries, validates UTF-8 metadata, and rejects:

- quoted or ambiguous patch paths;
- path traversal and any `.git` component;
- all `.github/` changes, so autonomous code cannot rewrite same-repository PR workflows or protection policy before review;
- `.gitattributes`, `.gitmodules`, transient OpenCode configuration, and the PR-message control file;
- renames, symbolic-link modes, and submodule modes.

The patch must pass `git apply --check` and `git diff --cached --check`. It is then applied, committed, and pushed with an empty trusted `core.hooksPath`. The publisher opens exactly one pull request and does not merge it.

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
- no autonomous `.github/` changes, merge, release, policy bypass, or unrelated refactoring.

Issue #86 still requires a separately reviewed benchmark workflow for full catalog probing, paired uncertainty, quality/latency/cost Pareto analysis, provenance, and retained evaluation artifacts. The hourly development broker is an execution boundary, not benchmark evidence.

## Dry run

A manual run with `dry_run: true` executes the queue and credential gates. When dispatch is permitted, it prints the exact bounded agent prompt to the workflow summary but does not build containers, start the broker, run OpenCode, upload an artifact, create a branch, or open a pull request.

## Failure semantics

A missing pull-request inventory, missing NIM secret, or open pull request produces a non-dispatch reason in the workflow summary. These states are safe no-ops, not successful evidence that development occurred.

When the broker cannot become ready or every model candidate fails, the workflow discards partial work and fails. An agent session that completes without changing the tree is reported as a no-op. An oversized, malformed, ambiguous, path-unsafe, policy-mutating, link-bearing, submodule-bearing, special-file-bearing, or otherwise invalid candidate fails closed before the publication token is used.

The cleanup step removes the broker, isolated networks, temporary agent image, provider configuration, and downloaded OpenCode archive even after failure.

## Operational verification

For a proposed workflow change, run:

```bash
python -m pytest -q tests/test_hourly_product_development_workflow.py
python -m pytest -q
```

Then require the current pull-request head to pass repository Tests, Fuzz, Security, Security Scan, SAST, central OpenCode review, CodeRabbit where configured, Noema, and every branch-protection check. The workflow is active only after it is merged into the default branch.

## Disabling the loop

Disable the scheduled workflow in GitHub Actions or remove only the `schedule` trigger through a reviewed pull request. Do not weaken the PR-first gate, container isolation, credential broker, candidate validation, fresh-runner publication, or independent-review requirements as a shortcut. Manual dry runs may remain available while scheduled dispatch is disabled.
