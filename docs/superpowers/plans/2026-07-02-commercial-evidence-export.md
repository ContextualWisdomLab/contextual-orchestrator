# Commercial Evidence Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `/api/v1/commercial_evidence_exports/latest` as a portable KRW 2,000,000,000 buyer due-diligence export index.

**Architecture:** Reuse the existing `saleability_decision_report()` chain and package its decision, blockers, warnings, runtime report links, buyer document links, Figma links, verification commands, review-process policy, and packaging decision into one local runtime report. Keep this in the unified control-plane product and expose it through the stdlib HTTP adapter, OpenAPI, admin observability panel, docs, tests, and FigJam.

**Tech Stack:** Python stdlib, in-memory `TaskOrchestrator`, stdlib HTTP server, embedded admin HTML/CSS/JS, markdown docs, Figma FigJam diagram generation. No Figma Code Connect.

## Global Constraints

- Figma Code Connect must not be used.
- Review process is not a blocker unless there is a concrete security, API contract, document, or product defect.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is a due-diligence target, not a valuation guarantee or purchase commitment.
- Data Analytics output must separate measured local evidence from proposed production or buyer-specific evidence.
- Korean and English admin labels must remain aligned.
- No new repo dependencies.

---

### Task 1: Runtime Report And HTTP Endpoint

**Files:**
- Modify: `contextual_orchestrator/orchestrator.py`
- Modify: `contextual_orchestrator/server.py`
- Test: `tests/test_commercial_evidence_export.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.saleability_decision_report(target_contract_value_krw, locale_bundles, security_profile) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_evidence_export_report(target_contract_value_krw, locale_bundles, security_profile) -> dict[str, Any]`
- Produces endpoint: `GET /api/v1/commercial_evidence_exports/latest`

- [x] **Step 1: Write the focused report test**

```python
report = orchestrator.commercial_evidence_export_report(
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
assert report["export_status"] == "commercial_export_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_evidence_export"
assert report["required_external_evidence"][0]["evidence_type"] == "proposed_until_production"
```

- [x] **Step 2: Implement the report**

```python
def commercial_evidence_export_report(...):
    saleability = self.saleability_decision_report(...)
    concrete_blockers = saleability["concrete_blockers"]
    required_external_evidence = [...]
    export_status = "commercial_export_blocked" if concrete_blockers else "commercial_export_ready_with_warnings"
    return {"export_status": export_status, "measurement_status": "local_commercial_evidence_export", ...}
```

- [x] **Step 3: Add the HTTP route**

```python
if path == "/api/v1/commercial_evidence_exports/latest":
    self._send(orchestrator.commercial_evidence_export_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [x] **Step 4: Run focused runtime test**

Run: `python tests/test_commercial_evidence_export.py`

Expected: `ok`

### Task 2: Contract, Admin, And Docs

**Files:**
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Create: `docs/commercial_evidence_export.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/figma_artifacts.md`
- Test: `tests/test_commercial_evidence_export.py`
- Test: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Produces OpenAPI operation id: `get_latest_commercial_evidence_export`
- Produces admin translation keys: `commercial_evidence_export_title`, `commercial_export_ready`, `commercial_export_ready_with_warnings`, `commercial_export_blocked`

- [x] **Step 1: Add OpenAPI path**

```python
"/api/v1/commercial_evidence_exports/latest": {
    "get": {
        "operationId": "get_latest_commercial_evidence_export",
        "summary": "Get portable commercial evidence export for buyer due diligence",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial evidence export"}},
    }
}
```

- [x] **Step 2: Add admin observability row**

```javascript
const commercialExport = state.commercialEvidenceExport || {};
const exportStatus = commercialExport.export_status || "commercial_export_blocked";
```

- [x] **Step 3: Add documentation**

```markdown
Runtime endpoint: `/api/v1/commercial_evidence_exports/latest`.
Figma Code Connect is not used.
Review process is not a blocker.
```

- [x] **Step 4: Run contract and artifact tests**

Run: `python tests/test_commercial_evidence_export.py && python tests/test_plugin_driven_artifacts.py && python tests/test_api_contract.py`

Expected: each command prints `ok`

### Task 3: Figma FigJam Diagram And Final Verification

**Files:**
- Modify: `docs/figma_artifacts.md`

**Interfaces:**
- Produces FigJam diagram: `KRW 2B Commercial Evidence Export`
- Reuses FigJam board: `https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M`

- [x] **Step 1: Generate FigJam diagram**

Use `generate_diagram` with `fileKey=Wr8iMlB9SHkerHSjv0Pe0M` and a flowchart that connects saleability, runtime reports, documents, Figma artifacts, verification commands, review policy, packaging decision, required external evidence, and export status.

- [x] **Step 2: Record the FigJam artifact**

Add `KRW 2B Commercial Evidence Export` to `docs/figma_artifacts.md`.

- [x] **Step 3: Run final verification**

Run:

```bash
python tests/test_commercial_evidence_export.py
python tests/test_saleability_decision.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: focused tests print `ok`, compileall succeeds, pytest passes, and diff check is clean.

- [ ] **Step 4: Commit and push**

```bash
git add contextual_orchestrator docs tests
git commit -m "feat: add commercial evidence export"
git push
```
