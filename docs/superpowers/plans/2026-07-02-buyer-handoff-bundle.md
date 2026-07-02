# Buyer Handoff Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a KRW 2,000,000,000 buyer handoff bundle that packages runtime readiness, evidence manifest, docs, Figma artifacts, verification commands, and explicit caveats into one reviewable API surface.

**Architecture:** Keep Contextual Orchestrator as one repository and one deployable control plane. Add a thin `TaskOrchestrator.buyer_handoff_bundle_report()` wrapper over existing readiness, analytics, and manifest reports, then wire it to `/api/v1/buyer_handoff_bundles/latest`, OpenAPI, admin observability, docs, and tests without a library split, submodule, new framework, or Figma Code Connect.

**Tech Stack:** Python stdlib runtime, stdlib HTTP server, embedded admin HTML, Markdown docs, existing FigJam board, assert-based Python tests, pytest.

## Global Constraints

- Figma Code Connect must not be used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is buyer due-diligence readiness, not guaranteed revenue, valuation, purchase approval, or production compliance certification.
- Keep `measured_local`, `repository_artifact`, `figma_artifact`, `proposed_until_production`, and `proposed_until_buyer_specific` claims separate.
- Do not add a runtime dependency or new framework.

---

### Task 1: Runtime Buyer Handoff Bundle

**Files:**

- Modify: `contextual_orchestrator/orchestrator.py`
- Create: `tests/test_buyer_handoff_bundle.py`

**Interfaces:**

- Consumes: `TaskOrchestrator.buyer_evidence_manifest_report(...)`, `commercial_readiness_report(...)`, `analytics_snapshot(...)`, repository docs, and security profile input.
- Produces: `TaskOrchestrator.buyer_handoff_bundle_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing report test**

Add a test that exercises runtime activity, calls:

```python
report = orchestrator.buyer_handoff_bundle_report(
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
assert report["bundle_status"] == "buyer_handoff_ready_with_warnings"
assert report["measurement_status"] == "local_buyer_handoff_bundle"
assert "not a valuation guarantee" in report["source_note"]
assert report["summary"]["by_completion_state"]["blocked"] == 0
assert report["included_artifacts"][0]["item_name"] == "runtime_reports"
assert report["included_artifacts"][0]["sources"] == [
    "/api/v1/sales_readiness/latest",
    "/api/v1/commercial_readiness/latest",
    "/api/v1/buyer_evidence_manifests/latest",
    "/api/v1/analytics_snapshots/latest",
]
assert report["follow_up_items"][0]["evidence_type"] == "proposed_until_production"
assert report["related_runtime_reports"]["buyer_manifest_status"] == "buyer_review_ready_with_warnings"
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```bash
python tests/test_buyer_handoff_bundle.py
```

Expected: failure because `buyer_handoff_bundle_report` is not defined.

- [ ] **Step 3: Implement the report**

Add `buyer_handoff_bundle_report(...)` to `contextual_orchestrator/orchestrator.py`. Reuse `_buyer_evidence_item(...)` and `_buyer_manifest_summary(...)` so artifact rows keep the same `item_name`, `reviewer`, `sources`, `evidence_type`, `completion_state`, `evidence`, and `next_action` shape as the buyer evidence manifest.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
python tests/test_buyer_handoff_bundle.py
```

Expected: `ok`.

### Task 2: API, Admin, And Artifact Records

**Files:**

- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Create: `docs/commercial_buyer_handoff_bundle.md`
- Modify: `docs/commercial_buyer_evidence_manifest.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**

- Consumes: `TaskOrchestrator.buyer_handoff_bundle_report(...)`.
- Produces: `GET /api/v1/buyer_handoff_bundles/latest`, operationId `get_latest_buyer_handoff_bundle`, and admin observability display of handoff status.

- [ ] **Step 1: Add API/admin/docs assertions**

Assert:

```python
assert "/api/v1/buyer_handoff_bundles/latest" in OPENAPI_SPEC["paths"]
assert OPENAPI_SPEC["paths"]["/api/v1/buyer_handoff_bundles/latest"]["get"]["operationId"] == "get_latest_buyer_handoff_bundle"
assert "/api/v1/buyer_handoff_bundles/latest" in ADMIN_HTML
assert "buyer_handoff_bundle_title" in ADMIN_TRANSLATIONS["en"]
assert "buyer_handoff_bundle_title" in ADMIN_TRANSLATIONS["ko"]
```

Also assert the new Markdown document contains `Commercial Buyer Handoff Bundle`, `Figma Code Connect is not used`, `Review process is not a blocker`, `Do not create a separate library, Git submodule, or extracted package now`, `KRW 2B Buyer Handoff Bundle Workflow`, and `/api/v1/buyer_handoff_bundles/latest`.

- [ ] **Step 2: Implement endpoint and admin fetch**

Add the server route, OpenAPI path, admin translations, admin `data-handoff-bundle-source`, fetch state, status chip, measurement status, and summary count.

- [ ] **Step 3: Update docs**

Document the endpoint in README and REST API design. Add `docs/commercial_buyer_handoff_bundle.md` as the handoff checklist and link it from the manifest.

- [ ] **Step 4: Generate FigJam workflow**

Use Figma `generate_diagram` on board `Wr8iMlB9SHkerHSjv0Pe0M` with:

- `planKey`: `team::1408252278989737675`
- `name`: `KRW 2B Buyer Handoff Bundle Workflow`

The diagram must show measured runtime reports, repository packet, Figma artifacts, verification commands, production follow-up, buyer-specific follow-up, and concrete defect handling.

- [ ] **Step 5: Verify contracts**

Run:

```bash
python tests/test_buyer_handoff_bundle.py
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
git add README.md contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py contextual_orchestrator/api_contract.py contextual_orchestrator/admin.py docs/rest_api_design.md docs/commercial_buyer_handoff_bundle.md docs/commercial_buyer_evidence_manifest.md docs/figma_artifacts.md docs/superpowers/plans/2026-07-02-buyer-handoff-bundle.md tests/test_buyer_handoff_bundle.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: expose buyer handoff bundle endpoint"
```

- [ ] **Step 3: Push and update PR**

Run:

```bash
git push origin product-plugin-driven-planning
gh pr edit 14 --body-file /tmp/contextual-orchestrator-pr14-body.md
gh pr checks 14
```

Expected: required checks pass or remain in progress without concrete failure. Review process delay remains a non-blocker.
