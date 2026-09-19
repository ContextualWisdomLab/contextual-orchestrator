# Commercial Close Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_close_readiness_report()` and `/api/v1/commercial_close_readiness/latest` so KRW 2,000,000,000 buyer close review can inspect repo-local sellable product evidence separately from buyer signatures, DPA/security acceptance, budget/PO, and go-live authorization gaps.

**Architecture:** Keep one repository and one deployable enterprise control plane. Add a thin `TaskOrchestrator.commercial_close_readiness_report()` wrapper over `commercial_value_readiness_report()`, `commercial_security_attestation_report()`, `commercial_contract_readiness_report()`, `commercial_onboarding_readiness_report()`, `commercial_operations_readiness_report()`, and `commercial_evidence_export_report()`, then expose it through `/api/v1/commercial_close_readiness/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib HTTP server, existing `TaskOrchestrator`, static admin HTML/JS, Markdown docs, pytest-compatible assert tests, Figma FigJam diagram.

## Global Constraints

- No new repo dependencies.
- Figma Code Connect is not used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- Block only on concrete product defects, security failures, API contract failures, document mismatches, or Code Connect usage.
- Separate repo-local sellable product packet evidence from buyer-specific signatures, DPA/security acceptance, budget/PO, and go-live authorization.

---

### Task 1: Runtime Close Readiness Report

**Files:**
- Create: `tests/test_commercial_close_readiness.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_value_readiness_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_security_attestation_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_contract_readiness_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_onboarding_readiness_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_operations_readiness_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_evidence_export_report(...) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_close_readiness_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_close_readiness_report(
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
assert report["close_status"] == "commercial_close_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_close_readiness"
assert report["close_summary"]["blocked_count"] == 0
assert report["close_summary"]["warning_count"] == 4
assert report["close_summary"]["buyer_signature_gap_count"] == 4
assert report["close_items"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_commercial_close_readiness.py`

Expected: FAIL because `commercial_close_readiness_report` is not defined.

- [ ] **Step 3: Implement the runtime report**

Add `commercial_close_readiness_report(...)` to `contextual_orchestrator/orchestrator.py`.

Return:

- `close_status`
- `target_contract_value_krw`
- `target_contract_value_display`
- `measurement_status`
- `source_note`
- `close_summary`
- `close_items`
- `concrete_blockers`
- `close_status_rules`
- `review_process_policy`
- `related_runtime_reports`
- `library_split_decision`
- `plugin_traceability`
- `close_links`

- [ ] **Step 4: Run the focused test**

Run: `python tests/test_commercial_close_readiness.py`

Expected: PASS after endpoint/docs/admin are connected.

- [ ] **Step 5: Commit**

```bash
git add contextual_orchestrator/orchestrator.py tests/test_commercial_close_readiness.py
git commit -m "feat: add commercial close readiness report"
```

### Task 2: Endpoint, Admin, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Create: `docs/commercial_close_readiness.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_close_readiness_report(...)`
- Produces: `GET /api/v1/commercial_close_readiness/latest` with operationId `get_latest_commercial_close_readiness`

- [ ] **Step 1: Add the endpoint**

```python
if path == "/api/v1/commercial_close_readiness/latest":
    self._send(orchestrator.commercial_close_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add OpenAPI path**

```python
"/api/v1/commercial_close_readiness/latest": {
    "get": {
        "operationId": "get_latest_commercial_close_readiness",
        "summary": "Get commercial close readiness for buyer signature and go-live review",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial close readiness"}},
    }
}
```

- [ ] **Step 3: Add admin status**

Add translations for:

- `commercial_close_readiness_title`
- `commercial_close_ready`
- `commercial_close_ready_with_warnings`
- `commercial_close_blocked`

Fetch `/api/v1/commercial_close_readiness/latest`, store it as `commercialCloseReadiness`, and show a status chip plus `close warning/blocked` summary.

- [ ] **Step 4: Add docs and artifact contract**

Create `docs/commercial_close_readiness.md` with these phrases:

- `Commercial Close Readiness`
- `KRW 2,000,000,000`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`
- `Close Readiness Inputs`
- `Runtime Shape`
- `Close Status Rules`
- `KRW 2B Commercial Close Readiness`
- `/api/v1/commercial_close_readiness/latest`
- `local_commercial_close_readiness`

- [ ] **Step 5: Run verification**

```bash
python tests/test_commercial_close_readiness.py
python tests/test_commercial_value_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_close_readiness.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-close-readiness.md tests/test_commercial_close_readiness.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial close readiness"
```
