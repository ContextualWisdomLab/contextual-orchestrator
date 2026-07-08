# AGENTS.md

Cross-agent conventions for `contextual-orchestrator`, readable by any coding
agent (Claude, Codex, Cursor, opencode, …). Keep this file tool-agnostic.

<!-- BEGIN cwl-agent-guidance -->
## Agent guidance (CWL governance)

This repo inherits ContextualWisdomLab org governance. Follow it before you
push or open a PR.

### Security & review gate

- Every PR to `main` runs the required **Security** workflow
  (`.github/workflows/security.yml`). Its jobs: **CodeQL** (code scanning),
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
- **Known deviation to migrate:** this repo currently resolves provider API
  keys from env — `ModelClient` reads `os.environ.get(agent.api_key_env)` in
  `contextual_orchestrator/orchestrator.py` (and `CONTEXTUAL_ORCHESTRATOR_*`
  tokens in `__main__.py`). Move these to KV-backed reads; keep env only as the
  bootstrap path that seeds the KV.

### This repo: the org LLM gateway

- `contextual-orchestrator` is the org's **LLM-communication hub** — the
  OpenAI-compatible front door consumed by **gyeot** and **scopeweave**.
- **Direction:** grow it toward a **LiteLLM-class multi-provider gateway**. The
  org is open to a **Rust/Python hybrid** to cut overhead.
- Its `ModelClient` currently reads `os.environ.get(agent.api_key_env)` — this
  is the KV-principle deviation above. Resolve the API key (including the org
  `OPENAI_API_KEY`) from the **KV / credential registry**, not env.
- The **OpenCode review pipeline is separate** and stays on **GitHub Models** —
  do not change it.

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
<!-- END cwl-agent-guidance -->
