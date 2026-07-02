# Saleability Decision Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a KRW 2,000,000,000 saleability decision gate that answers whether Contextual Orchestrator is ready for buyer diligence, ready with warnings, or blocked by a concrete defect.

**Architecture:** Keep one repository and one deployable product. Add `TaskOrchestrator.saleability_decision_report()` as a thin rollup over the existing buyer handoff bundle, then wire it to `/api/v1/saleability_decisions/latest`, OpenAPI, admin observability, docs, FigJam, and focused tests without Figma Code Connect, a new dependency, a submodule, or a library split.

**Tech Stack:** Python stdlib runtime, stdlib HTTP server, embedded admin HTML, Markdown docs, existing FigJam board, assert-based Python tests, pytest.

## Global Constraints

- Figma Code Connect must not be used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is buyer due-diligence readiness, not guaranteed revenue, valuation, purchase approval, or production compliance certification.
- Keep measured local evidence separate from production and buyer-specific follow-up evidence.
- Do not add a runtime dependency or new framework.

---

### Task 1: Runtime Saleability Decision

**Files:**

- Modify: `contextual_orchestrator/orchestrator.py`
- Create: `tests/test_saleability_decision.py`

**Interfaces:**

- Consumes: `TaskOrchestrator.buyer_handoff_bundle_report(...)`.
- Produces: `TaskOrchestrator.saleability_decision_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing report test**

Create `tests/test_saleability_decision.py` with a runtime exercise and:

```python
report = orchestrator.saleability_decision_report(
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
```

Assert:

```python
assert report["saleability_status"] == "saleability_ready_with_warnings"
assert report["measurement_status"] == "local_saleability_decision"
assert report["review_process_policy"]["is_blocker"] is False
assert report["concrete_blockers"] == []
assert report["warning_conditions"][0]["evidence_type"] == "proposed_until_production"
assert report["related_runtime_reports"]["buyer_handoff_status"] == "buyer_handoff_ready_with_warnings"
assert report["library_split_decision"]["decision"] == "keep_single_product"
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```bash
python tests/test_saleability_decision.py
```

Expected: failure because `saleability_decision_report` is not defined.

- [ ] **Step 3: Implement the report**

Add `saleability_decision_report(...)` to `contextual_orchestrator/orchestrator.py`. It should use the handoff bundle summary:

- blocked included artifacts -> `saleability_blocked`;
- no blocked artifacts but warning follow-ups -> `saleability_ready_with_warnings`;
- no blocked artifacts and no warnings -> `saleability_ready`.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
python tests/test_saleability_decision.py
```

Expected: `ok`.

### Task 2: API, Admin, And Docs

**Files:**

- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Create: `docs/commercial_saleability_decision.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**

- Consumes: `TaskOrchestrator.saleability_decision_report(...)`.
- Produces: `GET /api/v1/saleability_decisions/latest`, operationId `get_latest_saleability_decision`, and admin observability display of saleability status.

- [ ] **Step 1: Add API/admin/docs assertions**

Assert:

```python
assert "/api/v1/saleability_decisions/latest" in OPENAPI_SPEC["paths"]
assert OPENAPI_SPEC["paths"]["/api/v1/saleability_decisions/latest"]["get"]["operationId"] == "get_latest_saleability_decision"
assert "/api/v1/saleability_decisions/latest" in ADMIN_HTML
assert "saleability_decision_title" in ADMIN_TRANSLATIONS["en"]
assert "saleability_decision_title" in ADMIN_TRANSLATIONS["ko"]
```

Also assert `docs/commercial_saleability_decision.md` includes `Commercial Saleability Decision`, `Figma Code Connect is not used`, `Review process is not a blocker`, `Do not create a separate library, Git submodule, or extracted package now`, `KRW 2B Saleability Decision Gate`, and `/api/v1/saleability_decisions/latest`.

- [ ] **Step 2: Implement endpoint and admin fetch**

Add the server route, OpenAPI path, admin translations, admin `data-saleability-source`, fetch state, status chip, measurement status, and summary text.

- [ ] **Step 3: Update docs**

Document the endpoint in README and REST API design. Add `docs/commercial_saleability_decision.md` as the final saleability decision standard.

- [ ] **Step 4: Generate FigJam workflow**

Use Figma `generate_diagram` on board `Wr8iMlB9SHkerHSjv0Pe0M` with:

- `planKey`: `team::1408252278989737675`
- `name`: `KRW 2B Saleability Decision Gate`

The diagram must show buyer handoff bundle input, concrete blocker detection, review-process non-blocker policy, warning follow-ups, and ready or blocked saleability status.

- [ ] **Step 5: Verify contracts**

Run:

```bash
python tests/test_saleability_decision.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
```

Expected: all print `ok`.

### Task 3: Final Verification And PR Update

**Files:**

- No source files beyond Tasks 1 and 2.

**Interfaces:**

- Consumes: repository test commands and PR `#14`.
- Produces: pushed branch and updated PR evidence.

- [ ] **Step 1: Run final verification**

Run:

```bash
python tests/test_saleability_decision.py
python tests/test_buyer_handoff_bundle.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected:

- focused tests print `ok`;
- `compileall` exits 0;
- `pytest -q` reports all tests passing;
- `git diff --check` exits 0.

- [ ] **Step 2: Commit**

Run:

```bash
git add README.md contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py contextual_orchestrator/api_contract.py contextual_orchestrator/admin.py docs/rest_api_design.md docs/commercial_saleability_decision.md docs/figma_artifacts.md docs/superpowers/plans/2026-07-02-saleability-decision-gate.md tests/test_saleability_decision.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add saleability decision gate"
```

- [ ] **Step 3: Push and update PR**

Run:

```bash
git push origin product-plugin-driven-planning
gh pr edit 14 --body-file /tmp/contextual-orchestrator-pr14-body.md
gh pr checks 14
```

Expected: required checks pass or remain in progress without concrete failure. Review process delay remains a non-blocker.
