# Commercial Value Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_value_readiness_report()` and `/api/v1/commercial_value_readiness/latest` so KRW 2,000,000,000 buyer economic review can inspect repo-local value evidence separately from buyer-specific ROI, reference, budget, and payback gaps.

**Architecture:** Keep one repository and one deployable enterprise control plane. Add a thin `TaskOrchestrator.commercial_value_readiness_report()` wrapper over `commercial_readiness_report()`, `commercial_evidence_export_report()`, `commercial_security_attestation_report()`, and `analytics_snapshot()`, then expose it through `/api/v1/commercial_value_readiness/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib HTTP server, existing `TaskOrchestrator`, static admin HTML/JS, Markdown docs, pytest-compatible assert tests, Figma FigJam diagram.

## Global Constraints

- No new repo dependencies.
- Figma Code Connect is not used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- Block only on concrete product defects, security failures, API contract failures, document mismatches, or Code Connect usage.
- Separate measured local value evidence from buyer-specific ROI, reference, budget, and payback inputs.

---

### Task 1: Runtime Value Readiness Report

**Files:**
- Create: `tests/test_commercial_value_readiness.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_security_attestation_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_evidence_export_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_readiness_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.analytics_snapshot(...) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_value_readiness_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_value_readiness_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={
        "auth_mode": "split_token",
        "allow_public_bind": False,
        "expose_trace_by_default": False,
        "rate_limit_requests": 60,
        "max_concurrent_runs": 8,
    },
)
assert report["value_status"] == "commercial_value_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_value_readiness"
assert report["value_summary"]["blocked_count"] == 0
assert report["value_summary"]["warning_count"] == 4
assert report["value_summary"]["buyer_financial_gap_count"] == 4
assert report["value_items"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_commercial_value_readiness.py`

Expected: FAIL because `commercial_value_readiness_report` is not defined.

- [ ] **Step 3: Implement the runtime report**

Add `commercial_value_readiness_report(...)` to `contextual_orchestrator/orchestrator.py`.

Return:

- `value_status`
- `target_contract_value_krw`
- `target_contract_value_display`
- `measurement_status`
- `source_note`
- `value_summary`
- `value_items`
- `concrete_blockers`
- `value_status_rules`
- `review_process_policy`
- `related_runtime_reports`
- `library_split_decision`
- `plugin_traceability`
- `value_links`

- [ ] **Step 4: Run the focused test**

Run: `python tests/test_commercial_value_readiness.py`

Expected: PASS after endpoint/docs/admin are connected.

- [ ] **Step 5: Commit**

```bash
git add contextual_orchestrator/orchestrator.py tests/test_commercial_value_readiness.py
git commit -m "feat: add commercial value readiness report"
```

### Task 2: Endpoint, Admin, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Create: `docs/commercial_value_readiness.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_value_readiness_report(...)`
- Produces: `GET /api/v1/commercial_value_readiness/latest` with operationId `get_latest_commercial_value_readiness`

- [ ] **Step 1: Add the endpoint**

```python
if path == "/api/v1/commercial_value_readiness/latest":
    self._send(orchestrator.commercial_value_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add OpenAPI path**

```python
"/api/v1/commercial_value_readiness/latest": {
    "get": {
        "operationId": "get_latest_commercial_value_readiness",
        "summary": "Get commercial value readiness for buyer economic review",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial value readiness"}},
    }
}
```

- [ ] **Step 3: Add admin status**

Add translations for:

- `commercial_value_readiness_title`
- `commercial_value_ready`
- `commercial_value_ready_with_warnings`
- `commercial_value_blocked`

Fetch `/api/v1/commercial_value_readiness/latest`, store it as `commercialValueReadiness`, and show a status chip plus `value warning/blocked` summary.

- [ ] **Step 4: Add docs and artifact contract**

Create `docs/commercial_value_readiness.md` with these phrases:

- `Commercial Value Readiness`
- `KRW 2,000,000,000`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`
- `Value Readiness Inputs`
- `Runtime Shape`
- `Value Status Rules`
- `KRW 2B Commercial Value Readiness`
- `/api/v1/commercial_value_readiness/latest`
- `local_commercial_value_readiness`

- [ ] **Step 5: Run verification**

```bash
python tests/test_commercial_value_readiness.py
python tests/test_commercial_security_attestation.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_value_readiness.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-value-readiness.md tests/test_commercial_value_readiness.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial value readiness"
```
