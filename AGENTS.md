# AGENTS.md

Cache reuse is an item observation, not a request terminal until close. Preserve
mixed-batch selection timing, explicit failures and ContextVar cleanup. See
`docs/doctoring/kpi_stack_integration.md` for the RED cases and separate source
versus installed-core verification commands; do not weaken the native invariant.

Deferred batch lineage: read `docs/doctoring/batch_request_lineage.md` for the
HTTP reproduction, atomic submission-event projection, and remote/local failure
boundary. Do not retry a remotely submitted job after local lineage failure.

Workflow origin identity and persistence limitations are documented in
`docs/doctoring/workflow_request_link.md`; preserve origin on replacements and reload.

Cross-agent conventions for `contextual-orchestrator`, readable by any coding
agent (Claude, Codex, Cursor, opencode, …). Keep this file tool-agnostic.

## Autonomous research handoff

Identifier checks do not discover title-only citations. Verify their persistent
identifier and register it in both the citing document and paper inventory;
retain read-depth and reuse limits. See the KPI runbook's citation reconciliation.

Read [the KPI runbook](docs/doctoring/autonomous_kpi_runbook.md) before numerical
experiments and update its verified evidence before handoff. Choose KPI scope
autonomously under `docs/analytics_spec.md`. Preserve live execution handles;
high host load and silent numerical work are not proof of deadlock. Synthetic
recovery is unit evidence, not customer accuracy. Break owner/consumer release
cycles with isolated exact-revision contracts, never production source copies.

<!-- BEGIN cwl-agent-guidance -->
## Agent guidance (CWL governance)

This repo inherits ContextualWisdomLab org governance. Follow it before you
push or open a PR.

### Security & review gate

- Every PR to `main` runs the required **Security** workflow
  (`.github/workflows/security.yml`). Its jobs: tests and package quality,
  fuzzing, and **CodeQL** (code scanning),
  **Dependency review** (diff-scoped, `fail-on-severity: high`), **Python
  supply chain** (`pip-audit` against `requirements.lock` + CycloneDX SBOM), and
  **Trivy filesystem** (repo-wide, `severity: CRITICAL,HIGH`,
  `ignore-unfixed: true`). Merge is gated on these **job results**, not on any
  single tool's own rule.
- A failing **Trivy** or **pip-audit** job is a **REAL finding, not a flake.**
  Read the job log — it prints each finding's rule/advisory id, severity, and
  the affected package or file — or open the run's SARIF results in the
  Security tab. Then **remediate**:
  - Bump the offending dependency (this is a pinned, hash-locked project — edit
    `pyproject.toml` and regenerate `requirements.lock`, don't hand-edit hashes).
  - Only for a genuine false positive, add a **narrow, documented**
    `.trivyignore.yaml` entry (or a scoped `pip-audit --ignore-vuln` note)
    referencing the advisory id and why it doesn't apply.
  - Do **NOT** weaken, `continue-on-error`, or disable the gate.
- Reproduce Trivy locally against the merge result, not just your branch tip.
  A stale local DB misses findings:
  ```
  trivy --download-db-only
  trivy fs --severity CRITICAL,HIGH --ignore-unfixed .
  ```
- The org `code_scanning` ruleset is intentionally **CodeQL-only** — multiple
  code-scanning tools can't converge on one PR ref. Gating happens via the
  Security **job results**; do not add tools to the `code_scanning` rule.

### Code exploration

- Provider logs need server-generated per-request identity, not a session hash.
  Preserve context cleanup and validate the central collector before adoption.
  Reproduction and exact evidence: `docs/doctoring/provider_request_correlation.md`.

- This repo has **no `.codegraph/` index**, so use normal search
  (grep/ripgrep/find, file reads) to locate and understand code. If a
  `.codegraph/` directory is ever added at the repo root, prefer CodeGraph
  (`codegraph explore "<query>"`, or the code-review-graph MCP tools) BEFORE
  grep/find — it surfaces callers, callees, and impact that text search misses.

### Config & secrets (KV, not env)

- Do **NOT** read config or secrets via `os.getenv()` / raw environment
  variables at runtime. Read them from a **KV / credential registry**. Org
  Actions secrets (e.g. `OPENAI_API_KEY`) flow **into** the KV via a
  bootstrap/CI step; runtime reads from the KV — env is only transport into the
  KV, never the runtime source.
- The reference implementation is xtrmLLMBatchPython's pgcrypto-encrypted
  Postgres credential registry (`get_credential(name)`); reuse that pattern (a
  DB-backed KV is fine) unless a dedicated KV is adopted.
- Provider API keys are already resolved through the KV credential registry
  (`get_credential`) in `contextual_orchestrator/orchestrator.py`, and server
  bearer tokens are resolved the same way in `contextual_orchestrator/__main__.py`.
  `api_key_env` is preserved as a legacy field whose string value is treated as
  a KV credential name, not an environment variable to read. The only remaining
  permitted environment use is bootstrap transport to select and unlock the KV
  (see `docs/kv-credentials.md`).

### This repo: the org LLM gateway

- Endpoint races require a complete operator-reviewed equivalence contract.
  Never infer equivalence from provider/model names, and never treat missing loser
  usage as free or zero-cost execution.
- In structured fallback, keep the final error classification separate from
  per-attempt circuit and model-group observations. Record each actual failed
  candidate once before advancing or propagating a budget stop; a request-wide
  flag must not hide a later hard failure or charge an earlier error to a later
  413 candidate. Test real counters, not only mocked callback counts, including
  recovery, exhaustion, mixed failure order, and billed malformed output.
  Distinguish a malformed returned object from a client exception before
  return: reset response state per attempt, never copy prior usage, and keep
  unreported usage unavailable rather than fabricating a zero count.
  Apply this to repair calls that fail before returning as well. Exhausted
  malformed responses must not be classified as an all-provider size limit;
  test all-malformed and mixed malformed/413 orders before accepting that error.
- A stale-model response does not create a caller-selected endpoint constraint.
  Virtual structured recovery must visit the already-eligible distinct models,
  including later endpoint siblings, while preserving explicit model/endpoint,
  free/ZDR, file-replica, and effort restrictions. Test all-local-candidates
  failing, an initial candidate excluded during evidence collection, and billed
  malformed output on a later endpoint. Do not reject a review solely because
  an existing guard or successful-sibling test encodes the current behavior;
  verify the requirement and the exhausted-candidate case first.
- Review-gateway recovery tests must exercise `FREE_MODEL` with admitted free
  candidates, not only `AUTO_MODEL`. A mocked synthesis test does not prove
  the preceding conduct stages, HTTP boundary, or deployed Noema review.

- `contextual-orchestrator` is the org's **LLM-communication hub** — the
  OpenAI-compatible front door consumed by **gyeot** and **scopeweave**.
- **Direction:** grow it toward a **LiteLLM-class multi-provider gateway**. The
  org is open to a **Rust/Python hybrid** to cut overhead.
- Provider API keys and server bearer tokens are resolved from the **KV /
  credential registry** (`get_credential`), not from `os.environ`. Seed
  `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
  `OPENROUTER_API_KEY`, `OPENCODE_ZEN_API_KEY`, and any configured
  `OPENAI_API_KEY` into the KV at bootstrap so auto-discovery and routing can
  use them. One OpenCode Zen credential discovers the separate Zen and Go
  catalogs; only explicit zero-cost capability evidence admits either source
  to `orchestrator/free`.
- Tool-bearing chat requests stay synchronous. Reject explicit deferred/batch
  routing after applying `RoutingPolicy` precedence because the batch contract
  does not carry tool controls or returned tool calls. Generated planners,
  verifiers, and synthesizers suppress caller tools when the client supports
  that optional scope; structured virtual requests keep them on worker calls
  and strip them from final synthesis. Every grouped or `free_only`
  structured-synthesis attempt updates group stability exactly once, including
  failure followed by successful failover. A streamed failure before the first
  byte remains a trace step and usage row; missing provider usage is
  `unavailable`. HTTP 413 may fall back but never counts against member
  stability because it describes the request, not provider health.
- A live 2026-09-09 Bytez catalog check with a configured credential returned
  zero `task=chat` rows, while unfiltered and `text-generation` requests
  returned HTTP 500. Treat this as provider/runtime evidence, not proof of an
  endpoint or credential defect; keep Bytez absent from the active catalog
  until a non-empty authenticated listing succeeds.
- **Policy change (2026-08-18, explicit org decision, supersedes the prior
  "stays on GitHub Models" rule):** OpenCode, Noema, and Strix — the org's
  three-stage CI review pipeline defined in `ContextualWisdomLab/.github`
  (`opencode.jsonc`, `noema-review.yml`, `strix.yml`) — are being migrated to
  use `contextual-orchestrator` as their shared backend, with
  `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
  `OPENROUTER_API_KEY`, and `OPENCODE_ZEN_API_KEY` registered in this repo's
  KV so it auto-discovers their model catalogs and auto-optimizes routing by
  cost (see `contextual_orchestrator/model_discovery.py`, the
  `discover-models` CLI subcommand, and `ModelAgent.auth_scheme` for
  non-Bearer providers like Bytez). The provider-config change to the org
  repo itself lands as a separate, human-reviewed PR — this repo does not
  push or merge it automatically.

### This repo's role in the ecosystem

- **Role:** LLM gateway — token-cost optimizer + performance + upstream load
  balancer, covering beyond LiteLLM. KV-based keys; open to a Rust/Python
  hybrid.
- **Where it fits:** the org is an ecosystem around **naruon** (the hub:
  email/PIM that DOM-decomposes emails/files into a persisted knowledge graph).
  Each component below is a **standalone program that must ALSO work as a git
  submodule**, grown separately and together:
  - **waf-ids-ai-soc** — WAF / IDS / AI SOC / LB / APIM.
  - **clearfolio** — document viewer.
  - **pg-erd-cloud** — ERD tool.
  - **contextual-orchestrator** — this repo: LLM cost/perf/upstream-LB gateway
    (beyond LiteLLM).
  - **codec-carver** — STT / omni-modal speech-video codec.
  - **fast-mlsirm** — LLM-as-a-Judge calibration + evaluation-item quality
    (uses aFIPC FIPC + kaefa item-fit).
  - **feelanet-adfs** — passwordless SSO (OIDC/SCIM/ADFS/LDAP/FIDO2/OAuth2.1,
    eliminate passwords).
  - **newsdom-api** — PDF→DOM sidecar.
  - **semantic-data-portal** — upper ontology / catalog / governance plane with
    its own graph engine.

### Research grounding (attach paper PDFs)

- **Org rule:** substantive feature or process PRs should locate the relevant
  academic papers and **commit their PDFs into the PR** (e.g. a `docs/papers/`
  or `references/` directory) with full citations.
- **Respect copyright:** attach the PDF only when redistribution is permissible;
  otherwise **cite + link + summary** in place of the file.
- **This repo's angle:** ground routing/gateway work in the literature on
  cost-optimal LLM routing, upstream load balancing, and latency/throughput
  scheduling (e.g. LLM-cascade / model-routing and queueing/load-balancing
  papers).
- **Issue #568 slice:** `contextual_orchestrator.reasoning_effort_profile`
  is the provider-neutral role catalog and equal-budget true-θ ablation.
  RMSE is computed from θ̂ versus known true parameters, not a rank
  constant. Do not change production route/conduct defaults until
  `production_default_change_allowed` is true. Temperature is not effort.
<!-- END cwl-agent-guidance -->

## Stacked quality checks

For Noema incidents, `caller attempts=1` does not count internal provider
attempts. Match request identifiers and deployed revision before attributing
fallback; preflight failures are not review-request evidence. Keep ambiguous
timeout/502 replay separate from explicit rejection. See the
[attribution runbook](docs/doctoring/autonomous_kpi_runbook.md#noema-terminal-failure-attribution-2026-09-09).

Zero check runs on a stacked PR can mean its base was excluded by
`pull_request.branches: [main]`, not that checks passed. Keep the repository
quality trigger unfiltered and validate `tests/test_repository_security_metadata.py`
plus actionlint. After a new head, verify actual hosted execution; previous-head
results are historical. See the [reproduction runbook](docs/doctoring/autonomous_kpi_runbook.md#stacked-quality-trigger-repair).

## Tool-call handoffs

Return worker tool calls before text-answer judging or later workflow roles;
a handoff does not establish completed tool execution or answer quality.
Preserve stream indices and request isolation. Reproduction and release-proof
boundaries are in [the tool fallback runbook](docs/doctoring/TOOL_EXECUTION_FALLBACKS.md#virtual-worker-handoff-regression-2026-09-08).
