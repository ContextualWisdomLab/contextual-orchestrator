# Commercial Completion Scorecard Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_completion_scorecard_report()` and `/api/v1/commercial_completion_scorecards/latest` so the KRW 2,000,000,000 program-completion standard is available as runtime evidence, not only as Markdown.

**Architecture:** Keep one repository and one deployable enterprise control plane. Reuse commercial readiness, GTM readiness, launch readiness, admin state, analytics snapshot, Figma artifact records, and plugin plans to build a thin completion scorecard with ready/warning/blocked rows.

**Tech Stack:** Python stdlib HTTP server, in-memory `TaskOrchestrator` reports, embedded admin HTML/JS, Markdown docs, assert-based tests, pytest.

## Global Constraints

- Figma Code Connect must not be used.
- Review process delay is not a blocker unless it reports a concrete product, security, API-contract, or document defect.
- No new repo dependencies.
- Do not create a separate library, Git submodule, or extracted package now.
- Separate measured local evidence from buyer-specific, production, and signature inputs.

---

### Task 1: Runtime Completion Scorecard

**Files:**
- Create: `tests/test_commercial_completion_scorecard.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `commercial_readiness_report(...) -> dict[str, Any]`
- Consumes: `commercial_go_to_market_readiness_report(...) -> dict[str, Any]`
- Consumes: `commercial_launch_readiness_report(...) -> dict[str, Any]`
- Consumes: `analytics_snapshot(...) -> dict[str, Any]`
- Consumes: `admin_state() -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_completion_scorecard_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_completion_scorecard_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["completion_status"] == "commercial_completion_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_completion_scorecard"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_commercial_completion_scorecard.py`
Expected: FAIL because `commercial_completion_scorecard_report` is not defined.

- [ ] **Step 3: Write minimal implementation**

Add `commercial_completion_scorecard_report(...)` after `commercial_launch_readiness_report(...)`. It returns status, summary counts, scorecard items, concrete blockers, status rules, related report statuses, plugin traceability, review policy, library split decision, and links.

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_commercial_completion_scorecard.py`
Expected: PASS.

### Task 2: API And Admin Exposure

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_completion_scorecard_report(...)`
- Produces: `GET /api/v1/commercial_completion_scorecards/latest` with operationId `get_latest_commercial_completion_scorecard`

- [ ] **Step 1: Add route and OpenAPI contract**

```python
if path == "/api/v1/commercial_completion_scorecards/latest":
    self._send(orchestrator.commercial_completion_scorecard_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add admin labels and summary tile**

Add `commercial_completion_scorecard_title`, `commercial_completion_ready`, `commercial_completion_ready_with_warnings`, and `commercial_completion_blocked` in English and Korean. Fetch the endpoint in the existing observability readiness grid.

- [ ] **Step 3: Run focused test**

Run: `python tests/test_commercial_completion_scorecard.py`
Expected: PASS.

### Task 3: Docs, Analytics, And Figma Records

**Files:**
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/commercial_completion_scorecard.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Produces: analytics metric `commercial_completion_warning_count`
- Produces: FigJam artifact note `KRW 2B Commercial Completion Runtime Scorecard`

- [ ] **Step 1: Update documentation**

Document `/api/v1/commercial_completion_scorecards/latest`, `local_commercial_completion_scorecard`, runtime shape, completion status rules, Code Connect exclusion, review-process non-blocker policy, and single-product packaging decision.

- [ ] **Step 2: Update artifact tests**

Extend `tests/test_plugin_driven_artifacts.py` so docs and plans require the new endpoint, measurement status, metric, FigJam artifact, and verification command.

- [ ] **Step 3: Run docs/artifact test**

Run: `python tests/test_plugin_driven_artifacts.py`
Expected: PASS.

### Task 4: Verification And Commit

**Files:**
- Modify only files listed above.

**Interfaces:**
- Produces: pushed PR branch with completion scorecard runtime increment.

- [ ] **Step 1: Run verification**

Run:

```bash
python tests/test_commercial_completion_scorecard.py
python tests/test_commercial_launch_readiness.py
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
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_completion_scorecard.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-completion-scorecard-runtime.md tests/test_commercial_completion_scorecard.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial completion scorecard runtime"
git push
```
