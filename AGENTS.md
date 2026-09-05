# AGENTS.md

Cross-agent conventions for `contextual-orchestrator`, readable by any coding
agent (Claude, Codex, Cursor, opencode, …). Keep this file tool-agnostic.

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

- `contextual-orchestrator` is the org's **LLM-communication hub** — the
  OpenAI-compatible front door consumed by **gyeot** and **scopeweave**.
- **Direction:** grow it toward a **LiteLLM-class multi-provider gateway**. The
  org is open to a **Rust/Python hybrid** to cut overhead.
- Provider API keys and server bearer tokens are resolved from the **KV /
  credential registry** (`get_credential`), not from `os.environ`. Ensure the
  org `OPENAI_API_KEY` (and `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
  `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`) is seeded into the KV at
  bootstrap time so auto-discovery and routing can use them.
- **Policy change (2026-08-18, explicit org decision, supersedes the prior
  "stays on GitHub Models" rule):** OpenCode, Noema, and Strix — the org's
  three-stage CI review pipeline defined in `ContextualWisdomLab/.github`
  (`opencode.jsonc`, `noema-review.yml`, `strix.yml`) — are being migrated to
  use `contextual-orchestrator` as their shared backend, with
  `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
  `OPENROUTER_API_KEY`, and `OPENAI_API_KEY` registered in this repo's KV so
  it auto-discovers models across all five and auto-optimizes routing by
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

## Recurring bug class: hardcoded review-cadence dates

- `contextual_orchestrator/nim_benchmark.py`'s fail-closed evidence gates — the
  module-level `ACTUAL_COST_EVIDENCE` dict's `valid_until_date` field (checked
  by `_require_current_actual_cost_evidence`), and any pricing-scenario file's
  own `valid_until_date` field (checked by `validate_live_pricing_scenario`) —
  are deliberately literal calendar dates meant to lapse and force a human
  re-review. **Never** "fix" a lapsed date by rewriting the production literal
  to a later date without an actual re-review of the cited source; that
  defeats the gate's purpose.
- Once wall-clock time crosses the recorded date, unrelated tests that reach
  `run_mode="live"` start failing — or, worse, silently lose branch coverage
  while still reporting green — for a reason unrelated to what they assert,
  because `_require_current_actual_cost_evidence`/`validate_live_pricing_scenario`
  intercepts them first. This exact bug class was diagnosed and repaired
  (on PR branches — see the currency caveat below) three separate times this
  cycle:
  - `tests/test_nim_benchmark.py` — five tests
    (`test_evaluation_contract_failure_publishes_no_artifacts`,
    `test_live_run_fails_closed_without_credential`,
    `test_live_run_end_to_end_offline`,
    `test_live_run_uses_default_transport_builder_when_none_given`,
    `test_cli_live_fails_closed_without_secret`) reached the evidence gate by
    accident (`PR #1070`, commit `b4cc6c6a`).
  - `tests/test_spend_analytics.py` — a `usage_source` mislabeling that only
    *looked* date-adjacent at first; the actual root cause was unrelated
    (per-model prompt-evidence scoping, not a date) (`PR #1071`).
  - `tests/test_nim_benchmark_release_acceptance.py` — two tests
    (`test_live_run_rejects_unreviewed_pricing_before_egress`,
    `test_live_run_rejects_incomplete_or_expired_pricing_before_egress`) whose
    `pytest.raises(match=...)` substrings (`"reviewed"` / `"expired"`) also
    match `_require_current_actual_cost_evidence`'s own expiry message once
    `ACTUAL_COST_EVIDENCE` lapses — so once it does, both tests keep reporting
    green while silently exercising the wrong gate and zeroing branch coverage
    on `validate_live_pricing_scenario`'s two fail-closed lines. Invisible in
    pass/fail output; only a branch-coverage report catches it (`PR #1070`'s
    third commit, `0eaca9f1`).
- Established fix pattern (reuse it, do not reinvent it): an **opt-in, NOT
  autouse**, pytest fixture named `current_actual_cost_evidence`, using
  `monkeypatch.setitem` on `ACTUAL_COST_EVIDENCE` to pin the window to real
  "now" for the duration of one test, requested by name only from the tests
  that need to get past the evidence-currency gate to reach the behavior they
  actually test. Making it autouse silently defeats the fail-closed gate for
  the whole file — do not do that. Before trusting a green run near this
  literal date, check *branch* coverage on `nim_benchmark.py` specifically,
  not just pass/fail counts.
- **Verify before trusting this bullet list, don't just copy it.** Re-checked
  directly against this exact checkout on 2026-09-05 (`origin/main` @
  `a080297d`, `PR #1073`, itself a same-day refresh of `ACTUAL_COST_EVIDENCE`
  to `reviewed_at_date=2026-09-05` / `valid_until_date=2026-10-05`): `PR
  #1070` and `PR #1071` above are still **open/Draft, not merged**.
  `tests/test_nim_benchmark.py`'s `_fresh_backend` fixture on `main` right now
  is `@pytest.fixture(autouse=True)` and unconditionally patches both evidence
  dates for every test in the file — the exact file-wide-autouse anti-pattern
  `PR #1070` exists to remove; there is currently no
  `current_actual_cost_evidence` opt-in fixture anywhere in that file on
  `main`. `tests/test_spend_analytics.py::test_exact_output_without_prompt_usage_is_explicitly_unavailable`
  is **currently failing** on `main` (`assert 'tokenizer' == 'mixed'`) — `PR
  #1071`'s fix hasn't landed. `tests/test_nim_benchmark_release_acceptance.py`'s
  two pricing-scenario tests still lack the fixture from `PR #1070`'s third
  commit; they pass today only because the just-refreshed evidence window
  hasn't lapsed yet — the coverage-zeroing failure re-arms itself on or after
  **2026-10-05** unless that fix (or an equivalent) lands first. Check actual
  PR/merge status yourself before relying on any "established fix" claim in
  this file, including this one.
- Before claiming a required-check failure on your own PR is not caused by
  your diff, reproduce the exact CI command
  (`.github/workflows/security.yml`'s "Tests and package quality" job,
  specifically its "Prove complete benchmark coverage and public docstrings"
  step) in a throwaway git worktree checked out at unmodified `origin/main`,
  rather than guessing from the stack trace alone. Confirmed directly in this
  session: that exact command block currently reports 99% branch coverage on
  unmodified `origin/main` (missing `434, 645, 671->682` in
  `contextual_orchestrator/nim_benchmark.py`) — pre-existing, reproduced
  identically with zero relation to any one PR's diff, and tracked as `issue
  #1075` rather than folded into `PR #1070`'s scope.

## Central review sidecar/egress gap (tracked, not yet closed)

- `scripts/ci/contextual_orchestrator_review_sidecar.sh` lives in
  `ContextualWisdomLab/.github` and is vendored/called by that repo's
  `noema-review.yml`, `strix.yml`, `opencode-review-dispatch.yml`, and
  `pr-review-autofix.yml`. Confirmed by reading the script directly from
  `.github`'s `main` on 2026-09-05, it still: requires at least one of the
  five raw provider secrets (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
  `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) injected as
  plain Actions `env:` on the calling step; `git clone`s this repository fresh
  (pinned via `ORCHESTRATOR_PIN_SHA`, which itself still defaults to an older
  `2e414d1...` commit, not this repo's current `main`) and
  `pip install --require-hashes`s it on the calling runner on every
  invocation; and runs model discovery (`discover_all_models` /
  `register_review_credentials`) in-process there. This is **not yet** the
  pre-built, immutable, secrets-free gateway artifact the org wants those four
  consumers to call instead.
- `contextual-orchestrator` issue `#1041` comment `5550412102` lists six
  concrete requirements a released gateway/client/schema/egress contract
  needs to meet before those four consumers can drop the five secrets and
  flip their runner egress policy from `audit` to `block`: an immutable
  versioned artifact with source SHA, digest/SBOM/provenance, and rollback
  identity; consumers holding only an explicit endpoint + scoped bearer/OIDC
  credential, never provider keys; import/startup free of hidden network
  traffic; typed outcomes that separate authoritative findings from
  gateway/provider/infra failure; fixed virtual model `orchestrator/free` with
  no consumer-selected fallback or repository-authored timeout; and an egress
  contract narrow enough for `harden-runner` to move from `audit` to `block`.
  `ContextualWisdomLab/.github` issue `#1759` tracks the consumer migration
  order onto that contract once it ships.
- **Do not describe this repo's routing as "already fully used via
  `orchestrator/free` with no NIM exposure" without checking both layers.**
  The model-selection config layer (`opencode.jsonc`'s `enabled_providers`,
  `OPENCODE_MODEL_CANDIDATES` in `opencode-review-dispatch.yml`) can be, and
  is, already correct — pinned to `contextual-orchestrator/orchestrator/free`
  only. That is a separate fact from whether the runtime egress/secrets shape
  (the sidecar bullet above) has closed; it has not. `ContextualWisdomLab/.github`
  `PR #1884` is the concrete cautionary tale: it originally titled and framed
  itself as confirming the review pipeline "already routes through
  `orchestrator/free`... Confirmed already implemented; no code change
  needed," conflating the two layers, and had to be corrected (commit
  `50de5f63`) after an independent re-check disputed the framing and
  re-verified it against exact `file:line` evidence (`strix.yml`'s injected
  secrets, the sidecar script's own clone/build/in-process-discovery lines,
  and `strix.yml`'s `harden-runner` still set to `egress-policy: audit`) that
  the sidecar/egress layer was still open. State the two layers separately
  every time; do not let "the config is correct" imply "the secrets/egress
  gap is closed."
