# Commercial Acceptance Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `/api/v1/commercial_acceptance_checks/latest` as the runtime buyer acceptance check over the KRW 2,000,000,000 commercial evidence export.

**Architecture:** Reuse `TaskOrchestrator.commercial_evidence_export_report()` as the acceptance input. Add a thin acceptance report that classifies local runtime, document, admin, verification, Figma, review-policy, and packaging evidence as ready, warning, or blocked, then expose it through the stdlib HTTP adapter, OpenAPI, admin observability panel, docs, tests, and FigJam.

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
- Test: `tests/test_commercial_acceptance_check.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_evidence_export_report(target_contract_value_krw, locale_bundles, security_profile) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_acceptance_check_report(target_contract_value_krw, locale_bundles, security_profile) -> dict[str, Any]`
- Produces endpoint: `GET /api/v1/commercial_acceptance_checks/latest`

- [x] **Step 1: Write the focused report test**

```python
report = orchestrator.commercial_acceptance_check_report(
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
assert report["acceptance_status"] == "commercial_acceptance_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_acceptance_check"
assert report["follow_up_items"][0]["evidence_type"] == "proposed_until_production"
```

- [x] **Step 2: Implement the report**

```python
def commercial_acceptance_check_report(...):
    evidence_export = self.commercial_evidence_export_report(...)
    acceptance_items = [...]
    follow_up_items = [...]
    return {"acceptance_status": status, "measurement_status": "local_commercial_acceptance_check", ...}
```

- [x] **Step 3: Add the HTTP route**

```python
if path == "/api/v1/commercial_acceptance_checks/latest":
    self._send(orchestrator.commercial_acceptance_check_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [x] **Step 4: Run focused runtime test**

Run: `python tests/test_commercial_acceptance_check.py`

Expected: `ok`

### Task 2: Contract, Admin, And Docs

**Files:**
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Create: `docs/commercial_acceptance_check.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/figma_artifacts.md`
- Test: `tests/test_commercial_acceptance_check.py`
- Test: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Produces OpenAPI operation id: `get_latest_commercial_acceptance_check`
- Produces admin translation keys: `commercial_acceptance_check_title`, `commercial_acceptance_ready`, `commercial_acceptance_ready_with_warnings`, `commercial_acceptance_blocked`

- [x] **Step 1: Add OpenAPI path**

```python
"/api/v1/commercial_acceptance_checks/latest": {
    "get": {
        "operationId": "get_latest_commercial_acceptance_check",
        "summary": "Get commercial acceptance check for buyer due diligence",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial acceptance check"}},
    }
}
```

- [x] **Step 2: Add admin observability row**

```javascript
const commercialAcceptance = state.commercialAcceptanceCheck || {};
const acceptanceStatus = commercialAcceptance.acceptance_status || "commercial_acceptance_blocked";
```

- [x] **Step 3: Add documentation**

```markdown
Runtime endpoint: `/api/v1/commercial_acceptance_checks/latest`.
Figma Code Connect is not used.
Review process is not a blocker.
```

- [x] **Step 4: Run contract and artifact tests**

Run: `python tests/test_commercial_acceptance_check.py && python tests/test_plugin_driven_artifacts.py && python tests/test_api_contract.py`

Expected: each command prints `ok`

### Task 3: Figma FigJam Diagram And Final Verification

**Files:**
- Modify: `docs/figma_artifacts.md`

**Interfaces:**
- Produces FigJam diagram: `KRW 2B Commercial Acceptance Check`
- Reuses FigJam board: `https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M`

- [x] **Step 1: Generate FigJam diagram**

Use `generate_diagram` with `fileKey=Wr8iMlB9SHkerHSjv0Pe0M` and a flowchart that connects commercial evidence export, runtime chain, buyer packet, admin surface, verification, Figma artifacts, review policy, packaging decision, external gaps, and acceptance status.

- [x] **Step 2: Record the FigJam artifact**

Add `KRW 2B Commercial Acceptance Check` to `docs/figma_artifacts.md`.

- [x] **Step 3: Run final verification**

Run:

```bash
python tests/test_commercial_acceptance_check.py
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
git add README.md contextual_orchestrator docs tests
git commit -m "feat: add commercial acceptance check"
git push
```
