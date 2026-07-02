# Commercial Go-To-Market Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_go_to_market_readiness_report()` and `/api/v1/commercial_go_to_market_readiness/latest` so KRW 2,000,000,000 buyer and stakeholder review can inspect one GTM readiness index while buyer signatures, external proof, and production telemetry remain explicit warnings.

**Architecture:** Keep one repository and one deployable enterprise control plane. Add a thin `TaskOrchestrator.commercial_go_to_market_readiness_report()` wrapper over `commercial_close_readiness_report()`, `commercial_value_readiness_report()`, `commercial_security_attestation_report()`, `commercial_evidence_export_report()`, `buyer_handoff_bundle_report()`, `saleability_decision_report()`, and `analytics_snapshot()`, then expose it through `/api/v1/commercial_go_to_market_readiness/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib HTTP server, existing `TaskOrchestrator`, static admin HTML/JS, Markdown docs, pytest-compatible assert tests, Figma FigJam diagram.

## Global Constraints

- No new repo dependencies.
- Figma Code Connect is not used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- Block only on concrete product defects, security failures, API contract failures, document mismatches, or Code Connect usage.
- Separate repo-local GTM packet evidence from buyer-specific signatures, DPA/security acceptance, budget/PO, reference proof, external attestation, and production telemetry.

---

### Task 1: Runtime Go-To-Market Readiness Report

**Files:**
- Create: `tests/test_commercial_go_to_market_readiness.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_close_readiness_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_value_readiness_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_security_attestation_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.commercial_evidence_export_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.buyer_handoff_bundle_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.saleability_decision_report(...) -> dict[str, Any]`
- Consumes: `TaskOrchestrator.analytics_snapshot(...) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_go_to_market_readiness_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_go_to_market_readiness_report(
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
assert report["go_to_market_status"] == "commercial_go_to_market_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_go_to_market_readiness"
assert report["go_to_market_summary"]["blocked_count"] == 0
assert report["go_to_market_summary"]["warning_count"] == 2
assert report["go_to_market_summary"]["buyer_signature_gap_count"] == 4
assert report["go_to_market_items"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_commercial_go_to_market_readiness.py`

Expected: FAIL because `commercial_go_to_market_readiness_report` is not defined.

- [ ] **Step 3: Implement the runtime report**

Add `commercial_go_to_market_readiness_report(...)` to `contextual_orchestrator/orchestrator.py`.

Return:

- `go_to_market_status`
- `target_contract_value_krw`
- `target_contract_value_display`
- `measurement_status`
- `source_note`
- `go_to_market_summary`
- `go_to_market_items`
- `concrete_blockers`
- `go_to_market_status_rules`
- `review_process_policy`
- `related_runtime_reports`
- `library_split_decision`
- `plugin_traceability`
- `go_to_market_links`

- [ ] **Step 4: Run the focused test**

Run: `python tests/test_commercial_go_to_market_readiness.py`

Expected: PASS after endpoint/docs/admin are connected.

- [ ] **Step 5: Commit**

```bash
git add contextual_orchestrator/orchestrator.py tests/test_commercial_go_to_market_readiness.py
git commit -m "feat: add commercial go-to-market readiness report"
```

### Task 2: Endpoint, Admin, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Create: `docs/commercial_go_to_market_readiness.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_go_to_market_readiness_report(...)`
- Produces: `GET /api/v1/commercial_go_to_market_readiness/latest` with operationId `get_latest_commercial_go_to_market_readiness`

- [ ] **Step 1: Add the endpoint**

```python
if path == "/api/v1/commercial_go_to_market_readiness/latest":
    self._send(orchestrator.commercial_go_to_market_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add OpenAPI path**

```python
"/api/v1/commercial_go_to_market_readiness/latest": {
    "get": {
        "operationId": "get_latest_commercial_go_to_market_readiness",
        "summary": "Get commercial go-to-market readiness for buyer and stakeholder review",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial go-to-market readiness"}},
    }
}
```

- [ ] **Step 3: Add admin status**

Add translations for:

- `commercial_go_to_market_readiness_title`
- `commercial_go_to_market_ready`
- `commercial_go_to_market_ready_with_warnings`
- `commercial_go_to_market_blocked`

Fetch `/api/v1/commercial_go_to_market_readiness/latest`, store it as `commercialGoToMarketReadiness`, and show a status chip plus `gtm warning/blocked` summary.

- [ ] **Step 4: Add docs and artifact contract**

Create `docs/commercial_go_to_market_readiness.md` with these phrases:

- `Commercial Go-To-Market Readiness`
- `KRW 2,000,000,000`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`
- `Go-To-Market Inputs`
- `Runtime Shape`
- `Go-To-Market Status Rules`
- `KRW 2B Commercial Go To Market Readiness`
- `/api/v1/commercial_go_to_market_readiness/latest`
- `local_commercial_go_to_market_readiness`

- [ ] **Step 5: Run verification**

```bash
python tests/test_commercial_go_to_market_readiness.py
python tests/test_commercial_close_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_go_to_market_readiness.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-go-to-market-readiness.md tests/test_commercial_go_to_market_readiness.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial go-to-market readiness"
```
