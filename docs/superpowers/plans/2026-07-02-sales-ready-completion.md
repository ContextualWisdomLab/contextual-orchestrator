# Sales-Ready Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a truthful sales-readiness gate for the unified OpenAI-compatible API and admin/evidence control-plane product.

**Architecture:** Keep the stdlib runtime and static admin console. Add a readiness report method to `TaskOrchestrator`, expose it through an admin-scoped REST endpoint, and render it inside the existing observability view. The report summarizes pilot readiness from local runtime/configuration evidence without claiming production telemetry.

**Tech Stack:** Python stdlib HTTP server, existing static admin HTML/JS, handwritten OpenAPI dict, Markdown docs, no new dependencies.

## Global Constraints

- Do not use Figma Code Connect.
- Do not split the product into Fugu, TRINITY, Conductor, or any other separate product.
- Do not add new runtime dependencies or migrate frameworks.
- Keep readiness labels truthful: process-local data is not production telemetry.
- Keep English and Korean operator copy in scope.
- Resource and operation names must stay lower snake_case and resource-oriented.

---

### Task 1: Sales Readiness Contract

**Files:**
- Create: `tests/test_sales_readiness.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.analytics_snapshot(locale_bundles=None) -> dict[str, Any]`
- Produces: `TaskOrchestrator.sales_readiness_report(locale_bundles=None, security_profile=None) -> dict[str, Any]`

- [x] **Step 1: Write the failing test**

Create `tests/test_sales_readiness.py` with tests that assert:

- a representative orchestrator returns `readiness_status == "sales_ready"` when split auth, no public bind, trace hidden by default, active agents, one chat request, one conducted trace, one evaluation, and complete EN/KO locale bundles are present;
- each criterion row has `criterion_name`, `status`, `label`, `evidence`, and `remediation`;
- a single-token local deployment returns a `warn` criterion rather than `fail`.

- [x] **Step 2: Run the focused test to verify RED**

Run:

```bash
python tests/test_sales_readiness.py
```

Expected: failure because `TaskOrchestrator` has no `sales_readiness_report`.

- [x] **Step 3: Implement the report**

Add `sales_readiness_report()` and small private helpers in
`contextual_orchestrator/orchestrator.py`. Compute pass/warn/fail criteria from
existing runtime state, analytics snapshot, locale parity, provider URLs, and
security profile facts.

- [x] **Step 4: Run focused test to verify GREEN**

Run:

```bash
python tests/test_sales_readiness.py
```

Expected: `ok`.

### Task 2: Endpoint, OpenAPI, And Admin Surface

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Modify: `tests/test_sales_readiness.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.sales_readiness_report(...)`
- Produces: `GET /api/v1/sales_readiness/latest`, operationId `get_latest_sales_readiness`

- [x] **Step 1: Extend the failing test**

Assert the OpenAPI path exists, the admin HTML references
`/api/v1/sales_readiness/latest`, and the endpoint returns the same report shape
over HTTP with admin authentication.

- [x] **Step 2: Run focused test to verify RED**

Run:

```bash
python tests/test_sales_readiness.py
```

Expected: failure because the endpoint and admin references do not exist.

- [x] **Step 3: Implement endpoint and UI hooks**

Add the endpoint in `server.py`, OpenAPI path in `api_contract.py`, and a compact
readiness panel in `admin.py` using existing styles and fetch patterns.

- [x] **Step 4: Run focused test to verify GREEN**

Run:

```bash
python tests/test_sales_readiness.py
```

Expected: `ok`.

### Task 3: Documentation And Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/product_planning.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`

**Interfaces:**
- Consumes: implemented readiness endpoint and report
- Produces: discoverable sales-readiness documentation

- [x] **Step 1: Update docs**

Document the readiness endpoint as a pilot/sales gate. State that it is based on
runtime/configuration evidence and is not a production compliance certificate.

- [x] **Step 2: Run full verification**

Run:

```bash
python tests/test_self_check.py &&
python tests/test_paper_contracts.py &&
python tests/test_admin_contract.py &&
python tests/test_conventions.py &&
python tests/test_api_contract.py &&
python tests/test_security_hardening.py &&
python tests/test_repository_security_metadata.py &&
python tests/test_product_planning_contract.py &&
python tests/test_plugin_driven_artifacts.py &&
python tests/test_governance_runtime.py &&
python tests/test_analytics_runtime.py &&
python tests/test_sales_readiness.py &&
python -m compileall contextual_orchestrator tests &&
git diff --check
```

Expected: all checks pass with exit code 0.

- [x] **Step 3: Run CLI and HTTP smoke**

Run the CLI with `examples/agents.mock.json`, then start or reuse the local
server and check `/admin`, `/v1/chat/completions`,
`/api/v1/analytics_snapshots/latest`, and `/api/v1/sales_readiness/latest`.

- [x] **Step 4: Commit and push**

Commit with:

```bash
git add README.md docs contextual_orchestrator tests
git commit -m "feat: add sales readiness gate"
git push origin product-plugin-driven-planning
```

Expected: branch pushed to PR #14 or its successor; review-bot delay remains
non-blocking for program completion.
