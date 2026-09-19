# Commercial Procurement Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a KRW 2,000,000,000 buyer due-diligence procurement readiness gate over the commercial gap register.

**Architecture:** Keep one repository and one deployable control plane. Add a thin `TaskOrchestrator.commercial_procurement_readiness_report()` wrapper over `commercial_gap_register_report()`, then expose it through `/api/v1/commercial_procurement_readiness/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib runtime, stdlib HTTP server, embedded admin HTML/JS, handwritten OpenAPI dict, Markdown docs, FigJam Mermaid diagram, assert-based Python tests, pytest. No new repo dependencies.

## Global Constraints

- Figma Code Connect is not used.
- Review process is not a blocker; only concrete security, API contract, document, or product defects block release.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is a buyer due-diligence target, not a valuation guarantee or purchase commitment.
- Keep Korean and English admin copy in parity.

---

### Task 1: Runtime Procurement Readiness

**Files:**
- Create: `tests/test_commercial_procurement_readiness.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_gap_register_report(...) -> dict[str, Any]`.
- Produces: `TaskOrchestrator.commercial_procurement_readiness_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_commercial_procurement_readiness.py` with assertions for:

```python
report = orchestrator.commercial_procurement_readiness_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["procurement_status"] == "commercial_procurement_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_procurement_readiness"
assert report["procurement_summary"]["blocked_count"] == 0
assert report["procurement_summary"]["warning_count"] == 2
assert report["procurement_summary"]["review_process_is_blocker"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python tests/test_commercial_procurement_readiness.py
```

Expected: failure because `commercial_procurement_readiness_report` is not defined.

- [ ] **Step 3: Implement the report**

Add `commercial_procurement_readiness_report(...)` to
`contextual_orchestrator/orchestrator.py`. Reuse
`commercial_gap_register_report(...)`. Return `procurement_status`,
`measurement_status`, `procurement_summary`, `procurement_items`,
`concrete_blockers`, `procurement_status_rules`, `review_process_policy`,
`related_runtime_reports`, `library_split_decision`, `plugin_traceability`, and
`procurement_links`.

- [ ] **Step 4: Run the focused report test**

Run:

```bash
python tests/test_commercial_procurement_readiness.py
```

Expected: the report test advances to endpoint/docs failures.

### Task 2: Endpoint, Admin, OpenAPI, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Create: `docs/commercial_procurement_readiness.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `commercial_procurement_readiness_report(...)`.
- Produces: `GET /api/v1/commercial_procurement_readiness/latest` with operationId `get_latest_commercial_procurement_readiness`.

- [ ] **Step 1: Add the endpoint and OpenAPI path**

Add a server branch:

```python
if path == "/api/v1/commercial_procurement_readiness/latest":
    self._send(orchestrator.commercial_procurement_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

Add the OpenAPI path with operationId
`get_latest_commercial_procurement_readiness`.

- [ ] **Step 2: Add admin observability status**

Add English and Korean keys:

```python
"commercial_procurement_readiness_title": "Commercial Procurement Readiness",
"commercial_procurement_ready": "Commercial procurement ready",
"commercial_procurement_ready_with_warnings": "Commercial procurement ready with warnings",
"commercial_procurement_blocked": "Commercial procurement blocked",
```

Fetch `/api/v1/commercial_procurement_readiness/latest`, store it as
`state.commercialProcurementReadiness`, render a status chip, and include
procurement warning/blocked counts in the readiness summary.

- [ ] **Step 3: Add buyer-facing docs**

Create `docs/commercial_procurement_readiness.md` with the stable phrases:
`Commercial Procurement Readiness`, `KRW 2B Commercial Procurement Readiness`,
`Figma Code Connect is not used`, `Review process is not a blocker`,
`Do not create a separate library, Git submodule, or extracted package now`,
`Procurement Inputs`, `Runtime Shape`, `Procurement Status Rules`,
`/api/v1/commercial_procurement_readiness/latest`, and
`local_commercial_procurement_readiness`.

- [ ] **Step 4: Run focused docs/API tests**

Run:

```bash
python tests/test_commercial_procurement_readiness.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
```

Expected: all pass.

### Task 3: FigJam And Final Verification

**Files:**
- Modify: `docs/figma_artifacts.md`

**Interfaces:**
- Consumes: existing FigJam board `Wr8iMlB9SHkerHSjv0Pe0M`.
- Produces: editable FigJam diagram `KRW 2B Commercial Procurement Readiness`.

- [ ] **Step 1: Generate the FigJam diagram**

Use the Figma `generate_diagram` tool with a supported Mermaid flowchart. Do
not use Figma Code Connect.

- [ ] **Step 2: Record the artifact**

Add `KRW 2B Commercial Procurement Readiness` to `docs/figma_artifacts.md` and
describe how local packet evidence and gap-register warnings produce ready,
warning, or blocked procurement status.

- [ ] **Step 3: Run full verification**

Run:

```bash
python tests/test_commercial_procurement_readiness.py
python tests/test_commercial_gap_register.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.
