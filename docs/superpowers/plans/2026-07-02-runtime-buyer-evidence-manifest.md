# Runtime Buyer Evidence Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the KRW 2,000,000,000 buyer evidence manifest as a runtime API
surface, not only a Markdown document.

**Architecture:** Keep Contextual Orchestrator as one repository and one
deployable control plane. Add `TaskOrchestrator.buyer_evidence_manifest_report()`,
`GET /api/v1/buyer_evidence_manifests/latest`, OpenAPI/admin wiring, and focused
contract tests that reuse existing readiness and analytics reports without new
dependencies, a library split, or a submodule.

**Tech Stack:** Python stdlib runtime, stdlib HTTP server, Markdown docs,
existing FigJam board, existing GitHub PR workflow.

## Global Constraints

- Figma Code Connect must not be used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is buyer due-diligence readiness, not guaranteed revenue,
  valuation, purchase approval, or production compliance certification.
- Keep `measured_local`, `repository_artifact`, `figma_artifact`,
  `proposed_until_production`, and `proposed_until_buyer_specific` claims
  separate.
- Do not add a runtime dependency or new framework.

---

### Task 1: Runtime Manifest Report

**Files:**

- Modify: `contextual_orchestrator/orchestrator.py`
- Create: `tests/test_buyer_evidence_manifest.py`

**Interfaces:**

- Consumes: `TaskOrchestrator.commercial_readiness_report(...)`,
  `TaskOrchestrator.analytics_snapshot(...)`, repository documentation files,
  and security readiness profile input.
- Produces: `TaskOrchestrator.buyer_evidence_manifest_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Add the failing report test**

Add a test that calls:

```python
report = orchestrator.buyer_evidence_manifest_report(
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

Assert `manifest_status == "buyer_review_ready_with_warnings"`,
`measurement_status == "local_buyer_evidence_manifest"`, no blocked items, and
separate `measured_local`, `repository_artifact`, `figma_artifact`,
`proposed_until_production`, and `proposed_until_buyer_specific` rows.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```bash
python tests/test_buyer_evidence_manifest.py
```

Expected: failure because `buyer_evidence_manifest_report` is not defined.

- [ ] **Step 3: Implement the report**

Add `buyer_evidence_manifest_report(...)`, `_buyer_evidence_item(...)`, and
`_buyer_manifest_summary(...)` to `contextual_orchestrator/orchestrator.py`.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
python tests/test_buyer_evidence_manifest.py
```

Expected: `ok`.

### Task 2: API, Admin, And Docs Contract

**Files:**

- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/commercial_buyer_evidence_manifest.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**

- Consumes: `TaskOrchestrator.buyer_evidence_manifest_report(...)`.
- Produces: `GET /api/v1/buyer_evidence_manifests/latest`, operationId
  `get_latest_buyer_evidence_manifest`, and admin observability display of
  buyer manifest status.

- [ ] **Step 1: Add API/admin contract assertions**

Assert:

```python
assert "/api/v1/buyer_evidence_manifests/latest" in OPENAPI_SPEC["paths"]
assert OPENAPI_SPEC["paths"]["/api/v1/buyer_evidence_manifests/latest"]["get"]["operationId"] == "get_latest_buyer_evidence_manifest"
assert "/api/v1/buyer_evidence_manifests/latest" in ADMIN_HTML
assert "buyer_evidence_manifest_title" in ADMIN_TRANSLATIONS["en"]
assert "buyer_evidence_manifest_title" in ADMIN_TRANSLATIONS["ko"]
```

- [ ] **Step 2: Implement endpoint and admin fetch**

Add the server route, OpenAPI path, admin translations, admin fetch, and
readiness summary display.

- [ ] **Step 3: Update docs and Figma artifact records**

Update README, REST API design, commercial buyer evidence manifest, and
`docs/figma_artifacts.md`. Record `KRW 2B Runtime Buyer Evidence Endpoint`.

- [ ] **Step 4: Generate FigJam workflow**

Use Figma `generate_diagram` on file
`https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M` with:

- `planKey`: `team::1408252278989737675`
- `name`: `KRW 2B Runtime Buyer Evidence Endpoint`

- [ ] **Step 5: Verify contracts**

Run:

```bash
python tests/test_buyer_evidence_manifest.py
python tests/test_plugin_driven_artifacts.py
```

Expected: both print `ok`.

### Task 3: Final Verification And PR Update

**Files:**

- No source files beyond Tasks 1 and 2.

**Interfaces:**

- Consumes: repository test commands and PR `#14`.
- Produces: pushed branch and updated PR evidence.

- [ ] **Step 1: Run final verification**

Run:

```bash
python tests/test_buyer_evidence_manifest.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected:

- both focused test files print `ok`;
- `compileall` exits 0;
- `pytest -q` reports all tests passing;
- `git diff --check` exits 0.

- [ ] **Step 2: Commit**

Run:

```bash
git add README.md contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py contextual_orchestrator/api_contract.py contextual_orchestrator/admin.py docs/rest_api_design.md docs/commercial_buyer_evidence_manifest.md docs/figma_artifacts.md docs/superpowers/plans/2026-07-02-runtime-buyer-evidence-manifest.md tests/test_buyer_evidence_manifest.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: expose buyer evidence manifest endpoint"
```

- [ ] **Step 3: Push and update PR**

Run:

```bash
git push origin product-plugin-driven-planning
gh pr edit 14 --body-file /tmp/contextual-orchestrator-pr14-body.md
gh pr checks 14
```

Expected: required checks pass or remain in progress without concrete failure.
Review process delay remains a non-blocker.

