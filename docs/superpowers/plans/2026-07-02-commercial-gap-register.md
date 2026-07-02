# Commercial Gap Register Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a KRW 2,000,000,000 buyer due-diligence gap register that converts commercial release-candidate warning gaps into owner/action rows.

**Architecture:** Keep one repository and one deployable control plane. Add a thin `TaskOrchestrator.commercial_gap_register_report()` wrapper over `commercial_release_candidate_report()`, then expose it through `/api/v1/commercial_gap_registers/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib runtime, stdlib HTTP server, embedded admin HTML/JS, handwritten OpenAPI dict, Markdown docs, FigJam Mermaid diagram, assert-based Python tests, pytest. No new repo dependencies.

## Global Constraints

- Figma Code Connect is not used.
- Review process is not a blocker; only concrete security, API contract, document, or product defects block release.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is a buyer due-diligence target, not a valuation guarantee or purchase commitment.
- Keep Korean and English admin copy in parity.

---

### Task 1: Runtime Gap Register

**Files:**
- Create: `tests/test_commercial_gap_register.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_release_candidate_report(...) -> dict[str, Any]`.
- Produces: `TaskOrchestrator.commercial_gap_register_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_commercial_gap_register.py` with assertions for:

```python
report = orchestrator.commercial_gap_register_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["gap_register_status"] == "commercial_gap_register_open"
assert report["measurement_status"] == "local_commercial_gap_register"
assert report["gap_summary"]["total_gap_count"] == 2
assert report["gap_summary"]["review_process_is_blocker"] is False
assert report["gap_items"][0]["gap_status"] == "production_input_required"
assert report["gap_items"][1]["gap_status"] == "buyer_input_required"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python tests/test_commercial_gap_register.py
```

Expected: failure because `commercial_gap_register_report` is not defined.

- [ ] **Step 3: Implement the report**

Add `commercial_gap_register_report(...)` to `contextual_orchestrator/orchestrator.py`. Reuse `commercial_release_candidate_report(...)`. Return `gap_register_status`, `measurement_status`, `gap_summary`, `gap_items`, `concrete_blockers`, `gap_status_rules`, `review_process_policy`, `related_runtime_reports`, `library_split_decision`, `plugin_traceability`, and `gap_register_links`.

- [ ] **Step 4: Run the focused report test**

Run:

```bash
python tests/test_commercial_gap_register.py
```

Expected: the report test advances to endpoint/docs failures.

### Task 2: Endpoint, Admin, OpenAPI, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Create: `docs/commercial_gap_register.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `commercial_gap_register_report(...)`.
- Produces: `GET /api/v1/commercial_gap_registers/latest` with operationId `get_latest_commercial_gap_register`.

- [ ] **Step 1: Add the endpoint and OpenAPI path**

Add a server branch:

```python
if path == "/api/v1/commercial_gap_registers/latest":
    self._send(orchestrator.commercial_gap_register_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

Add the OpenAPI path with operationId `get_latest_commercial_gap_register`.

- [ ] **Step 2: Add admin observability status**

Add English and Korean keys:

```python
"commercial_gap_register_title": "Commercial Gap Register",
"commercial_gap_register_clear": "Commercial gap register clear",
"commercial_gap_register_open": "Commercial gap register open",
"commercial_gap_register_blocked": "Commercial gap register blocked",
```

Fetch `/api/v1/commercial_gap_registers/latest`, store it as
`state.commercialGapRegister`, render a status chip, and include gap counts in
the readiness summary.

- [ ] **Step 3: Add buyer-facing docs**

Create `docs/commercial_gap_register.md` with the stable phrases:
`Commercial Gap Register`, `KRW 2B Commercial Gap Register`,
`Figma Code Connect is not used`, `Review process is not a blocker`,
`Do not create a separate library, Git submodule, or extracted package now`,
`Gap Inputs`, `Runtime Shape`, `Gap Status Rules`,
`/api/v1/commercial_gap_registers/latest`, and
`local_commercial_gap_register`.

- [ ] **Step 4: Run focused docs/API tests**

Run:

```bash
python tests/test_commercial_gap_register.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
```

Expected: all pass.

### Task 3: FigJam And Final Verification

**Files:**
- Modify: `docs/figma_artifacts.md`

**Interfaces:**
- Consumes: existing FigJam board `Wr8iMlB9SHkerHSjv0Pe0M`.
- Produces: editable FigJam diagram `KRW 2B Commercial Gap Register`.

- [ ] **Step 1: Generate the FigJam diagram**

Use the Figma `generate_diagram` tool with a supported Mermaid flowchart. Do
not use Figma Code Connect.

- [ ] **Step 2: Record the artifact**

Add `KRW 2B Commercial Gap Register` to `docs/figma_artifacts.md` and describe
how release-candidate external gaps become owner/action/status rows.

- [ ] **Step 3: Run full verification**

Run:

```bash
python tests/test_commercial_gap_register.py
python tests/test_commercial_release_candidate.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.
