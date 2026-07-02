# Commercial Saleability Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a final KRW 2,000,000,000 commercial saleability gate that wraps the existing saleability decision and investment committee memo into one go/no-go runtime packet.

**Architecture:** Keep one repository and one deployable enterprise control plane. Add `TaskOrchestrator.commercial_saleability_gate_report()` as a thin wrapper over `saleability_decision_report()` and `commercial_investment_committee_memo_report()`, then wire it to admin-only HTTP, OpenAPI, admin readiness, docs, analytics, FigJam artifact records, and focused tests.

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
- Create: `tests/test_commercial_saleability_gate.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_saleability_gate_report(...) -> dict[str, Any]`.
- Produces: focused red-green contract for the final commercial saleability gate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_commercial_saleability_gate.py` with direct runtime, endpoint, OpenAPI, admin, and docs assertions for:

```python
report = orchestrator.commercial_saleability_gate_report(
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
assert report["saleability_gate_status"] == "commercial_saleability_gate_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_saleability_gate"
assert report["go_no_go_recommendation"]["recommendation_status"] == "go_with_buyer_conditions"
assert report["gate_summary"]["blocked_count"] == 0
assert report["gate_summary"]["warning_count"] == 2
assert report["gate_summary"]["check_count"] == 9
assert report["review_process_policy"]["is_blocker"] is False
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python tests/test_commercial_saleability_gate.py
```

Expected: failure because `commercial_saleability_gate_report` and `/api/v1/commercial_saleability_gates/latest` do not exist.

---

### Task 2: Runtime Gate

**Files:**
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes:
  - `TaskOrchestrator.saleability_decision_report(...) -> dict[str, Any]`
  - `TaskOrchestrator.commercial_investment_committee_memo_report(...) -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_saleability_gate_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Implement the thin wrapper**

Add `commercial_saleability_gate_report()` after `commercial_investment_committee_memo_report()`. It should:

- call the existing saleability decision and investment committee memo reports;
- deduplicate concrete blockers;
- convert buyer authority and production/external proof gaps into two warning checks;
- return `commercial_saleability_gate_ready`, `commercial_saleability_gate_ready_with_warnings`, or `commercial_saleability_gate_blocked`;
- keep `measurement_status="local_commercial_saleability_gate"`;
- include `go_no_go_recommendation`, `gate_summary`, `gate_checks`, `required_runtime_endpoints`, `buyer_close_packet`, `metric_provenance`, `operator_next_actions`, `final_buyer_authority_gaps`, `review_process_policy`, `library_split_decision`, `plugin_traceability`, and `gate_links`.

- [ ] **Step 2: Verify the focused runtime contract**

Run:

```bash
python tests/test_commercial_saleability_gate.py
```

Expected: the direct runtime assertions pass, while endpoint/admin/docs assertions may still fail.

---

### Task 3: API And Admin Surface

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_saleability_gate_report(...)`.
- Produces:
  - `GET /api/v1/commercial_saleability_gates/latest`
  - OpenAPI operationId `get_latest_commercial_saleability_gate`
  - admin readiness chip and Korean/English status copy.

- [ ] **Step 1: Wire the server and OpenAPI path**

Add the admin-only route and OpenAPI path:

```python
"/api/v1/commercial_saleability_gates/latest": {
    "get": {
        "operationId": "get_latest_commercial_saleability_gate",
        "summary": "Get KRW 2B commercial saleability gate",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial saleability gate"}},
    }
}
```

- [ ] **Step 2: Wire admin readiness**

Add translations and state/fetch/render support for:

```text
commercial_saleability_gate_title
commercial_saleability_gate_ready
commercial_saleability_gate_ready_with_warnings
commercial_saleability_gate_blocked
```

- [ ] **Step 3: Verify endpoint/admin contract**

Run:

```bash
python tests/test_commercial_saleability_gate.py
python tests/test_api_contract.py
```

Expected: all focused endpoint, OpenAPI, and admin assertions pass except docs artifact assertions if docs are not yet updated.

---

### Task 4: Documentation And Analytics

**Files:**
- Create: `docs/commercial_saleability_gate.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: runtime endpoint `/api/v1/commercial_saleability_gates/latest`.
- Produces: durable buyer-facing docs and artifact tests.

- [ ] **Step 1: Add the saleability gate doc**

Create `docs/commercial_saleability_gate.md` with these exact concepts:

- `Commercial Saleability Gate`
- `Runtime endpoint: `/api/v1/commercial_saleability_gates/latest``
- `Runtime Shape`
- `Gate Status Rules`
- `KRW 2B Commercial Saleability Gate`
- `local_commercial_saleability_gate`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`

- [ ] **Step 2: Update README, REST API, analytics, and Figma artifact records**

Add the endpoint, doc link, metric `commercial_saleability_gate_warning_count`, and FigJam artifact note. Keep all metric claims labeled as local runtime or proposed until buyer/production evidence exists.

- [ ] **Step 3: Verify docs artifacts**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
python tests/test_commercial_saleability_gate.py
```

Expected: both pass.

---

### Task 5: FigJam And Final Verification

**Files:**
- Modify: `docs/figma_artifacts.md`

**Interfaces:**
- Consumes: Figma `generate_diagram`.
- Produces: FigJam diagram `KRW 2B Commercial Saleability Gate`.

- [ ] **Step 1: Generate the FigJam diagram**

Use `generate_diagram` with `fileKey=Wr8iMlB9SHkerHSjv0Pe0M`. The diagram must connect saleability decision, investment committee memo, concrete blocker detection, warning conditions, buyer close packet, metric provenance, review-process non-blocker policy, and final ready/blocked gate status.

- [ ] **Step 2: Run final verification**

Run:

```bash
python tests/test_commercial_saleability_gate.py
python tests/test_saleability_decision.py
python tests/test_commercial_investment_committee_memo.py
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
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_saleability_gate.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-03-commercial-saleability-gate.md tests/test_commercial_saleability_gate.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial saleability gate runtime"
git push -u origin codex/commercial-saleability-gate
```

Then create or update the PR and verify head SHA, status checks, mergeability, review decision, and unresolved review threads.
