# Commercial Release Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local KRW 2,000,000,000 buyer due-diligence release-candidate manifest for the unified Contextual Orchestrator product.

**Architecture:** Keep one repository and one deployable control plane. Add a thin `TaskOrchestrator.commercial_release_candidate_report()` wrapper over `commercial_acceptance_check_report()`, then expose it through `/api/v1/commercial_release_candidates/latest`, admin observability, OpenAPI, Markdown docs, FigJam traceability, and focused tests.

**Tech Stack:** Python stdlib runtime, stdlib HTTP server, embedded admin HTML/JS, handwritten OpenAPI dict, Markdown docs, FigJam Mermaid diagram, assert-based Python tests, pytest. No new repo dependencies.

## Global Constraints

- Figma Code Connect is not used.
- Review process is not a blocker; only concrete security, API contract, document, or product defects block release.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is a buyer due-diligence target, not a valuation guarantee or purchase commitment.
- Keep Korean and English admin copy in parity.

---

### Task 1: Runtime Release-Candidate Report

**Files:**
- Create: `tests/test_commercial_release_candidate.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_acceptance_check_report(...) -> dict[str, Any]`.
- Produces: `TaskOrchestrator.commercial_release_candidate_report(...) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_commercial_release_candidate.py` with assertions for:

```python
report = orchestrator.commercial_release_candidate_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["release_status"] == "commercial_release_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_release_candidate"
assert report["release_summary"]["blocked_count"] == 0
assert report["release_summary"]["warning_count"] == 2
assert report["release_summary"]["review_process_is_blocker"] is False
assert report["library_split_decision"]["decision"] == "keep_single_product"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python tests/test_commercial_release_candidate.py
```

Expected: failure because `commercial_release_candidate_report` is not defined.

- [ ] **Step 3: Implement the report**

Add `commercial_release_candidate_report(...)` to `contextual_orchestrator/orchestrator.py`. Reuse `_buyer_evidence_item(...)` and `_buyer_manifest_summary(...)`. Return `release_status`, `measurement_status`, `release_summary`, `release_artifacts`, `external_release_gaps`, `concrete_blockers`, `review_process_policy`, `related_runtime_reports`, `library_split_decision`, `plugin_traceability`, and `release_links`.

- [ ] **Step 4: Run the focused report test**

Run:

```bash
python tests/test_commercial_release_candidate.py
```

Expected: the report test advances to endpoint/docs failures.

### Task 2: Endpoint, Admin, OpenAPI, And Docs

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Create: `docs/commercial_release_candidate.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `commercial_release_candidate_report(...)`.
- Produces: `GET /api/v1/commercial_release_candidates/latest` with operationId `get_latest_commercial_release_candidate`.

- [ ] **Step 1: Add the endpoint and OpenAPI path**

Add a server branch:

```python
if path == "/api/v1/commercial_release_candidates/latest":
    self._send(orchestrator.commercial_release_candidate_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

Add the OpenAPI path with operationId `get_latest_commercial_release_candidate`.

- [ ] **Step 2: Add admin observability status**

Add English and Korean keys:

```python
"commercial_release_candidate_title": "Commercial Release Candidate",
"commercial_release_ready": "Commercial release ready",
"commercial_release_ready_with_warnings": "Commercial release ready with warnings",
"commercial_release_blocked": "Commercial release blocked",
```

Fetch `/api/v1/commercial_release_candidates/latest`, store it as
`state.commercialReleaseCandidate`, render a status chip, and include release
blocked/warning counts in the readiness summary.

- [ ] **Step 3: Add buyer-facing docs**

Create `docs/commercial_release_candidate.md` with the stable phrases:
`Commercial Release Candidate`, `KRW 2B Commercial Release Candidate`,
`Figma Code Connect is not used`, `Review process is not a blocker`,
`Do not create a separate library, Git submodule, or extracted package now`,
`Release Inputs`, `Runtime Shape`, `Release Status Rules`,
`/api/v1/commercial_release_candidates/latest`, and
`local_commercial_release_candidate`.

- [ ] **Step 4: Run focused docs/API tests**

Run:

```bash
python tests/test_commercial_release_candidate.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
```

Expected: all pass.

### Task 3: FigJam And Final Verification

**Files:**
- Modify: `docs/figma_artifacts.md`

**Interfaces:**
- Consumes: existing FigJam board `Wr8iMlB9SHkerHSjv0Pe0M`.
- Produces: editable FigJam diagram `KRW 2B Commercial Release Candidate`.

- [ ] **Step 1: Generate the FigJam diagram**

Use the Figma `generate_diagram` tool with a supported Mermaid flowchart. Do
not use Figma Code Connect.

- [ ] **Step 2: Record the artifact**

Add `KRW 2B Commercial Release Candidate` to `docs/figma_artifacts.md` and
describe how acceptance, runtime endpoints, repository packet, security
metadata, admin visibility, verification, Figma artifacts, review process
policy, packaging decision, and external gaps flow into the release status.

- [ ] **Step 3: Run full verification**

Run:

```bash
python tests/test_commercial_release_candidate.py
python tests/test_commercial_acceptance_check.py
python tests/test_commercial_evidence_export.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected: all pass.
