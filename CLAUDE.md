# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read AGENTS.md first

`AGENTS.md` is the canonical, tool-agnostic agent operating guide for this repo. Read it fully and follow its guardrails before making changes. In particular:

- **Security gate**: every PR to `main` runs the required Security workflow. A failing Trivy or pip-audit job is a real finding — remediate by bumping the dependency and regenerating `requirements.lock`; never weaken, `continue-on-error`, or disable the gate.
- **KV, not env**: runtime config and provider secrets are resolved from the KV credential registry (`get_credential`), never `os.getenv` at request time. Env is only bootstrap transport into the KV (see `docs/kv-credentials.md`).
- **Org role**: this repo is the org's LLM gateway (cost optimizer + sync/batch routing + upstream load balancing, LiteLLM-plus scope), consumed by `gyeot` and `scopeweave`. The OpenCode review pipeline is separate, stays on GitHub Models, and must not be changed.
- **Research grounding**: substantive feature/process PRs should attach the relevant papers (PDF when redistribution is permissible, otherwise cite + link + summary) under `docs/papers/` with full citations.

This file complements AGENTS.md with commands and architecture; where they differ, AGENTS.md wins.

## Common commands

```bash
# Install (pinned, hash-locked — always this two-step form)
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .

# Full check suite (each test file is a directly runnable script; the
# canonical list is in README.md "Check")
python tests/test_self_check.py
python tests/test_paper_contracts.py
python tests/test_api_contract.py
# ... see README.md for the full list

# Or via pytest (conftest.py excludes the Atheris fuzz/ dir from collection)
python -m pytest tests -q

# Single test
python tests/test_self_check.py
python -m pytest tests/test_self_check.py -q

# Hypothesis property tests (always-on fuzz seams)
python -m pytest tests/fuzz -q

# Atheris coverage-guided fuzzing (Python < 3.13, needs Clang/libFuzzer)
python fuzz/fuzz_request_body.py -max_total_time=60 fuzz/corpus/request_body

# CLI one-shot completion (mock agents, fully offline)
python -m contextual_orchestrator "your prompt" --agents examples/agents.mock.json

# Serve the OpenAI-compatible API + /admin console
export CONTEXTUAL_ORCHESTRATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m contextual_orchestrator --serve --agents examples/agents.mock.json --port 8000

# Loopback-only local dev server (auth disabled; loopback only)
./.superset/run.sh

# Measure orchestration vs single-worker baseline
python -m contextual_orchestrator --eval "prompt one" "prompt two"

# Seed a provider credential into the KV at bootstrap
echo "$OPENAI_API_KEY" | python -m contextual_orchestrator register-credential --name OPENAI_API_KEY --value-stdin

# Reproduce the Trivy security gate locally (against the merge result)
trivy --download-db-only
trivy fs --severity CRITICAL,HIGH --ignore-unfixed .

# Regenerate the runtime lockfile after editing pyproject.toml (never hand-edit hashes)
pip-compile --extra=api --extra=db --generate-hashes --output-file=requirements.lock pyproject.toml
# CI/fuzz requirement .txt files: recompile with the exact `uv pip compile
# --generate-hashes ...` command in each file's header comment
```

CI gates: `.github/workflows/security.yml` (CodeQL + pip-audit on `requirements.lock` + CycloneDX SBOM; dependency review, Trivy, OSV, and Scorecard run org-centrally), `.github/workflows/fuzz.yml` (Hypothesis property tests + bounded Atheris runs), and the org-central OpenCode review pipeline (its pinned tools live in `requirements-opencode-review-ci.txt`: pytest, coverage, and `interrogate` docstring coverage with `fail-under = 80` from `pyproject.toml`).

## What this is

A stdlib-Python lab implementing a single OpenAI-compatible API that routes, delegates, verifies, and synthesizes work across a configurable pool of model agents — plus the org's cost-review and sync-vs-batch routing hub. Runtime dependencies are the Python standard library only (Hypothesis is the sole listed dependency, for the property tests); FastAPI/SQLAlchemy/psycopg exist as *optional* extras for the hardened production target, not the current runtime.

## Architecture

### Control flow

1. `server.py` (stdlib `BaseHTTPRequestHandler` delivery adapter) authenticates the Bearer token, validates the JSON body, message roles, mode, size, and rate before anything runs.
2. `TaskOrchestrator.complete()` in `orchestrator.py` picks one of two paths:
   - **Fast path (`route`)**: select a single worker for simple or latency-sensitive requests.
   - **Deep path (`conduct`)**: build a natural-language workflow of `thinker → worker → verifier → synthesizer` steps. Each `WorkflowStep` carries an **access list** so a worker sees only the prior outputs deliberately exposed to it.
3. `ModelClient` (infrastructure adapter) executes each step against `mock://` agents (offline, used by tests) or OpenAI-compatible HTTPS providers, with jittered retries for transient errors, failover to the next capability-matched agent, and a per-agent circuit breaker. Provider keys come from the KV via `get_credential`; egress to loopback/private/reserved addresses is blocked.
4. The answer is framed as an OpenAI `chat.completion` (or SSE `chat.completion.chunk` stream). Full orchestration traces are only returned to trusted callers.

### Modules (`contextual_orchestrator/`)

- `orchestrator.py` — the domain heart: `ModelAgent`, `WorkflowStep`, `OrchestrationPolicy`, `ModelClient`, `TaskOrchestrator`, secret/PII redaction, budget enforcement, spend analytics, and the commercial-readiness report generators behind `/api/v1/*`. Domain code stays here until a second implementation forces extraction (see `docs/code_conventions.md`).
- `server.py` — HTTP delivery adapter and `SecurityConfig`; all request validation lives here.
- `admin.py` — static HTML/CSS/JS for the `/admin` operator console (stays inline while the product is dependency-free).
- `credentials.py` / `kv_config.py` — the KV seam: `get_credential`/`register_credential` over pluggable backends (`InMemoryCredentialBackend` default; pgcrypto-encrypted `PostgresCredentialBackend`, selected via `CONTEXTUAL_ORCHESTRATOR_KV_BACKEND`).
- `cost_ledger.py` / `cost_router.py` / `batch_routing.py` / `token_counting.py` — the cost-review + routing hub: prompt-safe usage ledger with seven attribution dimensions, `RoutingPolicy` (sync vs batch from request hints + KV thresholds), and the [pg-llm-batch](https://github.com/ContextualWisdomLab/pg-llm-batch) batch/embeddings backends (a local in-process backend keeps the standalone path working with no external service).
- `api_contract.py` / `conventions.py` — API-shape and naming-rule enforcement helpers.
- `__main__.py` — the single entry point: CLI completion, `--serve`, `--eval`, and the `register-credential` bootstrap subcommand.

Agent pools are **data, not code**: `examples/agents.mock.json` and `examples/agents.openai.json`. State is in-memory by default; `--state-db PATH` persists runs/audit/analytics to sqlite.

### `conductor/` — context, not code

`conductor/` is the CDD (context-driven development) directory, not a Python package: `product.md` (intent and non-goals), `tech-stack.md` (stdlib-only rationale), `workflow.md` (the TDD/DDD/CDD method and the Ponytail design gate), `tracks.md` (active tracks). Update it when scope, dependencies, workflow, or domain terms change.

## Key conventions

- **TDD from papers**: paper claims (Fugu, TRINITY, Conductor — see `docs/architecture.md`) become executable contracts in `tests/` *before* implementation changes. Many tests assert doc/API contracts, so behavior changes usually require updating the matching `docs/*.md` in the same PR.
- **Naming**: configurable, API, and DB object names must be lower snake_case with **two or more semantic words** (`agent_pool`, `workflow_run`; never `agent` or `agentPool`). Enforced by `conventions.require_object_name()` and `tests/test_conventions.py`. Paper role values (`thinker`, `worker`, `verifier`, `synthesizer`) are deliberate exceptions.
- **Ponytail design gate**: before adding a dependency or designing a subsystem, research existing libraries and record the decision in `docs/library_research.md`. No new dependency when the stdlib or an already selected library covers the need; no interface or factory until a second real implementation exists.
- **Honest metrics**: spend/analytics surfaces label estimates (`usage_source`, `measurement_status`) and never fabricate prices — preserve this when touching analytics.
- **Fuzz seams**: untrusted-input parsers (request body, agent config, redaction, orchestration) share invariant checks in `fuzz/targets.py`, driven by both Hypothesis (`tests/fuzz/`) and Atheris (`fuzz/`). New parsing seams should get a target there (see `docs/fuzzing.md`).
