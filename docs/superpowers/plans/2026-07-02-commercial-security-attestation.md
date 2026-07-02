# Commercial Security Attestation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_security_attestation_report()` and `/api/v1/commercial_security_attestations/latest` so KRW 2,000,000,000 buyer security review can inspect repo-local security evidence separately from external attestation and buyer privacy gaps.

**Architecture:** Keep one repository and one deployable enterprise control plane. Add a thin `TaskOrchestrator.commercial_security_attestation_report()` wrapper over `commercial_operations_readiness_report()`, then expose it through `/api/v1/commercial_security_attestations/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib HTTP server, existing `TaskOrchestrator`, static admin HTML/JS, Markdown docs, pytest-compatible assert tests, Figma FigJam diagram.

## Global Constraints

- No new repo dependencies.
- Figma Code Connect is not used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- Block only on concrete product defects, security failures, API contract failures, document mismatches, or Code Connect usage.
- Separate measured local security evidence from external attestation and buyer privacy inputs.

---

### Task 1: Runtime Security Attestation Report

**Files:**
- Create: `tests/test_commercial_security_attestation.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_operations_readiness_report(...) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_security_attestation_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_security_attestation_report(
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
assert report["security_attestation_status"] == "commercial_security_attestation_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_security_attestation"
assert report["security_attestation_summary"]["blocked_count"] == 0
assert report["security_attestation_summary"]["warning_count"] == 3
assert report["security_attestation_summary"]["external_attestation_gap_count"] == 2
assert report["security_attestation_summary"]["buyer_privacy_gap_count"] == 1
assert report["security_attestation_items"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_commercial_security_attestation.py`

Expected: FAIL because `commercial_security_attestation_report` is not defined.

- [ ] **Step 3: Implement the runtime report**

Add `commercial_security_attestation_report(...)` to `contextual_orchestrator/orchestrator.py`.

Return:

- `security_attestation_status`
- `target_contract_value_krw`
- `target_contract_value_display`
- `measurement_status`
- `source_note`
- `security_attestation_summary`
- `security_attestation_items`
- `concrete_blockers`
- `security_attestation_status_rules`
- `review_process_policy`
- `related_runtime_reports`
- `library_split_decision`
- `plugin_traceability`
- `security_attestation_links`

- [ ] **Step 4: Run the focused test**

Run: `python tests/test_commercial_security_attestation.py`

Expected: PASS after endpoint/docs/admin are connected.

- [ ] **Step 5: Commit**

```bash
git add contextual_orchestrator/orchestrator.py tests/test_commercial_security_attestation.py
git commit -m "feat: add commercial security attestation report"
```

### Task 2: Endpoint, Admin, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Create: `docs/commercial_security_attestation.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_security_attestation_report(...)`
- Produces: `GET /api/v1/commercial_security_attestations/latest` with operationId `get_latest_commercial_security_attestation`

- [ ] **Step 1: Add the endpoint**

```python
if path == "/api/v1/commercial_security_attestations/latest":
    self._send(orchestrator.commercial_security_attestation_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add OpenAPI path**

```python
"/api/v1/commercial_security_attestations/latest": {
    "get": {
        "operationId": "get_latest_commercial_security_attestation",
        "summary": "Get commercial security attestation for buyer security review",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial security attestation"}},
    }
}
```

- [ ] **Step 3: Add admin status**

Add translations for:

- `commercial_security_attestation_title`
- `commercial_security_attestation_ready`
- `commercial_security_attestation_ready_with_warnings`
- `commercial_security_attestation_blocked`

Fetch `/api/v1/commercial_security_attestations/latest`, store it as `commercialSecurityAttestation`, and show a status chip plus `security warning/blocked` summary.

- [ ] **Step 4: Add docs and artifact contract**

Create `docs/commercial_security_attestation.md` with these phrases:

- `Commercial Security Attestation`
- `KRW 2,000,000,000`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`
- `Security Attestation Inputs`
- `Runtime Shape`
- `Security Attestation Status Rules`
- `KRW 2B Commercial Security Attestation`
- `/api/v1/commercial_security_attestations/latest`
- `local_commercial_security_attestation`

- [ ] **Step 5: Run verification**

```bash
python tests/test_commercial_security_attestation.py
python tests/test_commercial_operations_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/commercial_security_attestation.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-security-attestation.md tests/test_commercial_security_attestation.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial security attestation"
```
