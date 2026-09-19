# Commercial Onboarding Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_onboarding_readiness_report()` and `/api/v1/commercial_onboarding_readiness/latest` so KRW 2,000,000,000 buyer close can turn production support/SLO and buyer-specific inputs into a paid-onboarding action plan.

**Architecture:** Keep one repository and one deployable enterprise control plane. Add a thin `TaskOrchestrator.commercial_onboarding_readiness_report()` wrapper over `commercial_contract_readiness_report()`, then expose it through `/api/v1/commercial_onboarding_readiness/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib HTTP server, existing `TaskOrchestrator`, static admin HTML/JS, Markdown docs, pytest-compatible assert tests, Figma FigJam diagram.

## Global Constraints

- No new repo dependencies.
- Figma Code Connect is not used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- Block only on concrete product defects, security failures, API contract failures, document mismatches, or Code Connect usage.
- Separate measured local analytics from proposed production onboarding telemetry.

---

### Task 1: Runtime Onboarding Report

**Files:**
- Create: `tests/test_commercial_onboarding_readiness.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_contract_readiness_report(...) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_onboarding_readiness_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_onboarding_readiness_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["onboarding_status"] == "commercial_onboarding_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_onboarding_readiness"
assert report["onboarding_summary"]["blocked_count"] == 0
assert report["onboarding_summary"]["warning_count"] == 2
assert report["onboarding_items"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_commercial_onboarding_readiness.py`

Expected: FAIL because `commercial_onboarding_readiness_report` is not defined.

- [ ] **Step 3: Implement the runtime report**

Add `commercial_onboarding_readiness_report(...)` to `contextual_orchestrator/orchestrator.py`.

Return:

- `onboarding_status`
- `target_contract_value_krw`
- `target_contract_value_display`
- `measurement_status`
- `source_note`
- `onboarding_summary`
- `onboarding_items`
- `concrete_blockers`
- `onboarding_status_rules`
- `review_process_policy`
- `related_runtime_reports`
- `library_split_decision`
- `plugin_traceability`
- `onboarding_links`

- [ ] **Step 4: Run the focused test**

Run: `python tests/test_commercial_onboarding_readiness.py`

Expected: PASS after endpoint/docs/admin are connected.

- [ ] **Step 5: Commit**

```bash
git add contextual_orchestrator/orchestrator.py tests/test_commercial_onboarding_readiness.py
git commit -m "feat: add commercial onboarding readiness report"
```

### Task 2: Endpoint, Admin, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Create: `docs/commercial_onboarding_readiness.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_onboarding_readiness_report(...)`
- Produces: `GET /api/v1/commercial_onboarding_readiness/latest` with operationId `get_latest_commercial_onboarding_readiness`

- [ ] **Step 1: Add the endpoint**

```python
if path == "/api/v1/commercial_onboarding_readiness/latest":
    self._send(orchestrator.commercial_onboarding_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add OpenAPI path**

```python
"/api/v1/commercial_onboarding_readiness/latest": {
    "get": {
        "operationId": "get_latest_commercial_onboarding_readiness",
        "summary": "Get commercial onboarding readiness for buyer close",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial onboarding readiness"}},
    }
}
```

- [ ] **Step 3: Add admin status**

Add translations for:

- `commercial_onboarding_readiness_title`
- `commercial_onboarding_ready`
- `commercial_onboarding_ready_with_warnings`
- `commercial_onboarding_blocked`

Fetch `/api/v1/commercial_onboarding_readiness/latest`, store it as `commercialOnboardingReadiness`, and show a status chip plus `onboarding warning/blocked` summary.

- [ ] **Step 4: Add docs and artifact contract**

Create `docs/commercial_onboarding_readiness.md` with these phrases:

- `Commercial Onboarding Readiness`
- `KRW 2,000,000,000`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`
- `Onboarding Inputs`
- `Runtime Shape`
- `Onboarding Status Rules`
- `KRW 2B Commercial Onboarding Readiness`
- `/api/v1/commercial_onboarding_readiness/latest`
- `local_commercial_onboarding_readiness`

- [ ] **Step 5: Run verification**

```bash
python tests/test_commercial_onboarding_readiness.py
python tests/test_commercial_contract_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/server.py docs/commercial_onboarding_readiness.md docs/figma_artifacts.md docs/rest_api_design.md tests/test_plugin_driven_artifacts.py
git commit -m "feat: expose commercial onboarding readiness"
```
