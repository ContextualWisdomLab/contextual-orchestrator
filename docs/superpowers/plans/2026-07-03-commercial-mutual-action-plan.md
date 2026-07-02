# Commercial Mutual Action Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a KRW 2,000,000,000 commercial mutual action plan that turns saleability evidence into buyer/seller execution milestones.

**Architecture:** Keep one repository and one deployable enterprise control plane. Add `TaskOrchestrator.commercial_mutual_action_plan_report()` as a thin wrapper over the commercial saleability gate and existing readiness reports, then expose it through admin-only HTTP, OpenAPI, admin readiness, docs, analytics, FigJam artifact records, and focused tests.

**Tech Stack:** Python stdlib HTTP server, in-memory `TaskOrchestrator`, Markdown docs, Figma FigJam diagram. No new dependencies.

## Global Constraints

- Figma Code Connect must not be used.
- Review process delay is not a blocker.
- Concrete security, API contract, document, runtime, or product failure is a blocker.
- Keep Contextual Orchestrator as one enterprise control-plane product.
- Do not create a separate library, Git submodule, extracted package, or framework migration now.
- Separate measured local runtime evidence from proposed production or buyer-specific evidence.
- Preserve Korean and English admin copy.

---

### Task 1: Focused Runtime Contract

**Files:**
- Create: `tests/test_commercial_mutual_action_plan.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_mutual_action_plan_report(...) -> dict[str, Any]`.
- Produces: focused red-green contract for buyer/seller execution milestones.

- [ ] **Step 1: Write the failing test**

Create `tests/test_commercial_mutual_action_plan.py` with direct runtime, endpoint, OpenAPI, admin, and docs assertions for:

```python
report = orchestrator.commercial_mutual_action_plan_report(
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
assert report["mutual_action_plan_status"] == "commercial_mutual_action_plan_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_mutual_action_plan"
assert report["plan_summary"]["milestone_count"] == 8
assert report["plan_summary"]["warning_count"] == 2
assert report["plan_summary"]["blocked_count"] == 0
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python tests/test_commercial_mutual_action_plan.py
```

Expected: failure because `commercial_mutual_action_plan_report` and `/api/v1/commercial_mutual_action_plans/latest` do not exist.

---

### Task 2: Runtime Action Plan

**Files:**
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes:
  - `TaskOrchestrator.commercial_saleability_gate_report(...) -> dict[str, Any]`
  - `TaskOrchestrator.commercial_investment_committee_memo_report(...) -> dict[str, Any]`
  - close, onboarding, operations, contract, procurement, value, and security readiness reports.
- Produces: `TaskOrchestrator.commercial_mutual_action_plan_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Implement the thin wrapper**

Add `commercial_mutual_action_plan_report()` after `commercial_saleability_gate_report()`. It should:

- call the existing saleability gate, investment committee memo, close, onboarding, operations, contract, procurement, value, security, analytics, and admin reports;
- return `commercial_mutual_action_plan_ready`, `commercial_mutual_action_plan_ready_with_warnings`, or `commercial_mutual_action_plan_blocked`;
- keep `measurement_status="local_commercial_mutual_action_plan"`;
- include `go_no_go_recommendation`, `plan_summary`, `milestones`, `required_runtime_endpoints`, `buyer_seller_owners`, `exit_criteria`, `buyer_authority_gaps`, `production_external_evidence_gaps`, `metric_provenance`, `operator_next_actions`, `review_process_policy`, `library_split_decision`, `plugin_traceability`, and `plan_links`.

- [ ] **Step 2: Verify the focused runtime contract**

Run:

```bash
python tests/test_commercial_mutual_action_plan.py
```

Expected: direct runtime assertions pass, while endpoint/admin/docs assertions may still fail.

---

### Task 3: API And Admin Surface

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_mutual_action_plan_report(...)`.
- Produces:
  - `GET /api/v1/commercial_mutual_action_plans/latest`
  - OpenAPI operationId `get_latest_commercial_mutual_action_plan`
  - admin readiness chip and Korean/English status copy.

- [ ] **Step 1: Wire the server and OpenAPI path**

Add the admin-only route and OpenAPI path:

```python
"/api/v1/commercial_mutual_action_plans/latest": {
    "get": {
        "operationId": "get_latest_commercial_mutual_action_plan",
        "summary": "Get KRW 2B commercial mutual action plan",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial mutual action plan"}},
    }
}
```

- [ ] **Step 2: Wire admin readiness**

Add translations and state/fetch/render support for:

```text
commercial_mutual_action_plan_title
commercial_mutual_action_plan_ready
commercial_mutual_action_plan_ready_with_warnings
commercial_mutual_action_plan_blocked
```

- [ ] **Step 3: Verify endpoint/admin contract**

Run:

```bash
python tests/test_commercial_mutual_action_plan.py
python tests/test_api_contract.py
```

Expected: all focused endpoint, OpenAPI, and admin assertions pass except docs artifact assertions if docs are not yet updated.

---

### Task 4: Documentation And Analytics

**Files:**
- Create: `docs/commercial_mutual_action_plan.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: runtime endpoint `/api/v1/commercial_mutual_action_plans/latest`.
- Produces: durable buyer/seller action-plan docs and artifact tests.

- [ ] **Step 1: Add the mutual action plan doc**

Create `docs/commercial_mutual_action_plan.md` with these exact concepts:

- `Commercial Mutual Action Plan`
- `Runtime endpoint: `/api/v1/commercial_mutual_action_plans/latest``
- `Runtime Shape`
- `Action Plan Status Rules`
- `KRW 2B Commercial Mutual Action Plan`
- `local_commercial_mutual_action_plan`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`

- [ ] **Step 2: Update README, REST API, analytics, and Figma artifact records**

Add the endpoint, doc link, metric `commercial_mutual_action_plan_warning_count`, and FigJam artifact note. Keep all metric claims labeled as local runtime or proposed until buyer/production evidence exists.

- [ ] **Step 3: Verify docs artifacts**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
python tests/test_commercial_mutual_action_plan.py
```

Expected: both pass.

---

### Task 5: FigJam And Final Verification

**Files:**
- Modify: `docs/figma_artifacts.md`

**Interfaces:**
- Consumes: Figma `generate_diagram`.
- Produces: FigJam diagram `KRW 2B Commercial Mutual Action Plan`.

- [ ] **Step 1: Generate the FigJam diagram**

Use `generate_diagram` with `fileKey=Wr8iMlB9SHkerHSjv0Pe0M`. The diagram must connect saleability gate, buyer/seller milestones, authority gaps, production evidence gaps, metric provenance, review-process non-blocker policy, and final ready/blocked action-plan status.

- [ ] **Step 2: Run final verification**

Run:

```bash
python tests/test_commercial_mutual_action_plan.py
python tests/test_commercial_saleability_gate.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all commands pass.

- [ ] **Step 3: Commit and publish**

Run:

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_mutual_action_plan.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-03-commercial-mutual-action-plan.md tests/test_commercial_mutual_action_plan.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial mutual action plan runtime"
git push
```

Then verify PR #15 head SHA, status checks, mergeability, review decision, and unresolved review threads.
