# Commercial Demo Scenarios Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_demo_scenario_report()` and `/api/v1/commercial_demo_scenarios/latest` so the KRW 2,000,000,000 buyer demo script is available as runtime evidence.

**Architecture:** Keep one repository and one deployable enterprise control plane. Reuse commercial completion, buyer acceptance workflow, analytics snapshot, admin state, docs, and Figma artifact records to produce persona-scoped demo steps with ready, warning, and blocked states.

**Tech Stack:** Python stdlib HTTP server, in-memory `TaskOrchestrator` reports, embedded admin HTML/JS, Markdown docs, assert-based tests, pytest.

## Global Constraints

- Figma Code Connect must not be used.
- Review process delay is not a blocker unless it reports a concrete product, security, API-contract, or document defect.
- No new repo dependencies.
- Do not create a separate library, Git submodule, or extracted package now.
- Separate measured local evidence from buyer-specific, production, and signature inputs.

---

### Task 1: Runtime Demo Scenario Packet

**Files:**
- Create: `tests/test_commercial_demo_scenarios.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `commercial_completion_scorecard_report(...) -> dict[str, Any]`
- Consumes: `commercial_buyer_acceptance_workflow_report(...) -> dict[str, Any]`
- Consumes: `analytics_snapshot(...) -> dict[str, Any]`
- Consumes: `admin_state() -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_demo_scenario_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_demo_scenario_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["demo_status"] == "commercial_demo_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_demo_scenarios"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_commercial_demo_scenarios.py`
Expected: FAIL because `commercial_demo_scenario_report` is not defined.

- [ ] **Step 3: Write minimal implementation**

Add `commercial_demo_scenario_report(...)` after `commercial_buyer_acceptance_workflow_report(...)`. It returns demo narrative, persona-scoped demo steps, runtime endpoints, status rules, related runtime reports, plugin traceability, review policy, library split decision, and links.

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_commercial_demo_scenarios.py`
Expected: PASS.

### Task 2: API And Admin Exposure

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_demo_scenario_report(...)`
- Produces: `GET /api/v1/commercial_demo_scenarios/latest` with operationId `get_latest_commercial_demo_scenarios`

- [ ] **Step 1: Add route and OpenAPI contract**

```python
if path == "/api/v1/commercial_demo_scenarios/latest":
    self._send(orchestrator.commercial_demo_scenario_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add admin labels and summary tile**

Add `commercial_demo_scenarios_title`, `commercial_demo_ready`, `commercial_demo_ready_with_warnings`, and `commercial_demo_blocked` in English and Korean. Fetch the endpoint in the existing observability readiness grid.

- [ ] **Step 3: Run focused test**

Run: `python tests/test_commercial_demo_scenarios.py`
Expected: PASS.

### Task 3: Docs, Analytics, And Figma Records

**Files:**
- Create: `docs/commercial_demo_scenarios.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Produces: analytics metric `commercial_demo_warning_count`
- Produces: FigJam artifact note `KRW 2B Commercial Demo Scenarios`

- [ ] **Step 1: Update documentation**

Document `/api/v1/commercial_demo_scenarios/latest`, `local_commercial_demo_scenarios`, runtime shape, demo status rules, Code Connect exclusion, review-process non-blocker policy, and single-product packaging decision.

- [ ] **Step 2: Update artifact tests**

Extend `tests/test_plugin_driven_artifacts.py` so docs and plans require the new endpoint, measurement status, metric, FigJam artifact, and verification command.

- [ ] **Step 3: Run docs/artifact test**

Run: `python tests/test_plugin_driven_artifacts.py`
Expected: PASS.

### Task 4: Verification And Commit

**Files:**
- Modify only files listed above.

**Interfaces:**
- Produces: pushed PR branch with commercial demo scenario runtime increment.

- [ ] **Step 1: Run verification**

Run:

```bash
python tests/test_commercial_demo_scenarios.py
python tests/test_commercial_completion_scorecard.py
python tests/test_commercial_buyer_acceptance_workflow.py
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
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_demo_scenarios.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-demo-scenarios-runtime.md tests/test_commercial_demo_scenarios.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial demo scenarios runtime"
git push
```
