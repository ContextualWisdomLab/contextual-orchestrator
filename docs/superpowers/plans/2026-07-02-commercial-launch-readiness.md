# Commercial Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_launch_readiness_report()` and `/api/v1/commercial_launch_readiness/latest` so a KRW 2,000,000,000 buyer can review launch/trial execution readiness without confusing repo-local evidence with buyer, production, or signature inputs.

**Architecture:** Keep Contextual Orchestrator as one enterprise control-plane product. Add a thin launch gate that reuses go-to-market, operations, onboarding, acceptance, analytics, and admin evidence; expose it through the stdlib server, OpenAPI, admin readiness summary, docs, analytics spec, FigJam artifact record, and focused tests.

**Tech Stack:** Python stdlib HTTP server, in-memory `TaskOrchestrator` reports, embedded admin HTML/JS, Markdown docs, pytest-compatible assert tests.

## Global Constraints

- Figma Code Connect must not be used.
- Review process delay is not a blocker unless it reports a concrete product, security, API-contract, or document defect.
- No new repo dependencies.
- Do not create a separate library, Git submodule, or extracted package now.
- Separate measured local evidence from buyer-specific, production, and signature inputs.

---

### Task 1: Runtime Launch Gate

**Files:**
- Create: `tests/test_commercial_launch_readiness.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `commercial_go_to_market_readiness_report(...) -> dict[str, Any]`, `commercial_operations_readiness_report(...) -> dict[str, Any]`, `commercial_onboarding_readiness_report(...) -> dict[str, Any]`, `commercial_acceptance_check_report(...) -> dict[str, Any]`, `analytics_snapshot(...) -> dict[str, Any]`, `admin_state() -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_launch_readiness_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_launch_readiness_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["launch_status"] == "commercial_launch_ready_with_warnings"
assert report["launch_summary"]["external_input_group_count"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_commercial_launch_readiness.py`
Expected: FAIL because `commercial_launch_readiness_report` is not defined.

- [ ] **Step 3: Write minimal implementation**

Add `commercial_launch_readiness_report(...)` after `commercial_go_to_market_readiness_report(...)`. It returns `launch_status`, `measurement_status`, `launch_summary`, `launch_items`, status rules, related runtime report statuses, review-process policy, library split decision, plugin traceability, and links.

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_commercial_launch_readiness.py`
Expected: PASS.

### Task 2: API And Admin Exposure

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_launch_readiness_report(...)`
- Produces: `GET /api/v1/commercial_launch_readiness/latest` with operationId `get_latest_commercial_launch_readiness`

- [ ] **Step 1: Add route and OpenAPI contract**

```python
if path == "/api/v1/commercial_launch_readiness/latest":
    self._send(orchestrator.commercial_launch_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add admin translations and readiness tile**

Add English and Korean labels for `commercial_launch_readiness_title`, `commercial_launch_ready`, `commercial_launch_ready_with_warnings`, and `commercial_launch_blocked`. Fetch and render the launch status beside the existing commercial GTM status.

- [ ] **Step 3: Run focused contract test**

Run: `python tests/test_commercial_launch_readiness.py`
Expected: PASS.

### Task 3: Commercial Docs And Artifact Records

**Files:**
- Create: `docs/commercial_launch_readiness.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Produces: launch readiness doc, analytics metric `commercial_launch_external_input_count`, FigJam artifact note `KRW 2B Commercial Launch Readiness`

- [ ] **Step 1: Add docs**

Document the launch inputs, runtime shape, status rules, Code Connect exclusion, review-process non-blocker policy, and single-product packaging decision.

- [ ] **Step 2: Add artifact assertions**

Extend `tests/test_plugin_driven_artifacts.py` so docs and plans must mention the new endpoint, measurement status, analytics metric, FigJam artifact, and verification command.

- [ ] **Step 3: Run docs/artifact test**

Run: `python tests/test_plugin_driven_artifacts.py`
Expected: PASS.

### Task 4: Verification And Commit

**Files:**
- Modify only files listed above.

**Interfaces:**
- Produces: pushed PR branch with verified launch readiness increment

- [ ] **Step 1: Run verification**

Run:

```bash
python tests/test_commercial_launch_readiness.py
python tests/test_commercial_go_to_market_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.

- [ ] **Step 2: Commit and push**

Run:

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_launch_readiness.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-launch-readiness.md tests/test_commercial_launch_readiness.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial launch readiness"
git push
```
