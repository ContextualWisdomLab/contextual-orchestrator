# Commercial Purchase Approval Packet Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_purchase_approval_packet_report()` and `/api/v1/commercial_purchase_approval_packets/latest` so the KRW 2,000,000,000 buyer purchase approval packet is available as runtime evidence.

**Architecture:** Keep one repository and one deployable enterprise control plane. Reuse proposal packet, close readiness, procurement readiness, contract readiness, value readiness, security attestation, onboarding readiness, operations readiness, analytics snapshot, admin state, docs, and Figma artifact records to produce buyer-side approval gates with ready, warning, and blocked states.

**Tech Stack:** Python stdlib HTTP server, in-memory `TaskOrchestrator` reports, embedded admin HTML/JS, Markdown docs, assert-based tests, pytest.

## Global Constraints

- Figma Code Connect must not be used.
- Review process delay is not a blocker unless it reports a concrete product, security, API-contract, or document defect.
- No new repo dependencies.
- Do not create a separate library, Git submodule, or extracted package now.
- Separate measured local evidence from buyer-specific finance, procurement, legal, signature, production, and go-live authorization inputs.

---

### Task 1: Runtime Purchase Approval Packet

**Files:**
- Create: `tests/test_commercial_purchase_approval_packet.py`
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: `commercial_proposal_packet_report(...) -> dict[str, Any]`
- Consumes: `commercial_close_readiness_report(...) -> dict[str, Any]`
- Consumes: `commercial_procurement_readiness_report(...) -> dict[str, Any]`
- Consumes: `commercial_contract_readiness_report(...) -> dict[str, Any]`
- Consumes: `commercial_value_readiness_report(...) -> dict[str, Any]`
- Consumes: `commercial_security_attestation_report(...) -> dict[str, Any]`
- Consumes: `commercial_onboarding_readiness_report(...) -> dict[str, Any]`
- Consumes: `commercial_operations_readiness_report(...) -> dict[str, Any]`
- Consumes: `analytics_snapshot(...) -> dict[str, Any]`
- Consumes: `admin_state() -> dict[str, Any]`
- Produces: `TaskOrchestrator.commercial_purchase_approval_packet_report(...) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_purchase_approval_packet_report(
    target_contract_value_krw=2_000_000_000,
    locale_bundles=ADMIN_TRANSLATIONS,
    security_profile={"auth_mode": "split_token", "allow_public_bind": False},
)
assert report["purchase_approval_status"] == "commercial_purchase_approval_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_purchase_approval_packet"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_commercial_purchase_approval_packet.py`
Expected: FAIL because `commercial_purchase_approval_packet_report` is not defined.

- [ ] **Step 3: Write minimal implementation**

Add `commercial_purchase_approval_packet_report(...)` after `commercial_proposal_packet_report(...)`. It returns approval narrative, buyer-side approval gates, runtime endpoints, status rules, related runtime reports, plugin traceability, review policy, library split decision, and links.

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_commercial_purchase_approval_packet.py`
Expected: PASS.

### Task 2: API And Admin Exposure

**Files:**
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_purchase_approval_packet_report(...)`
- Produces: `GET /api/v1/commercial_purchase_approval_packets/latest` with operationId `get_latest_commercial_purchase_approval_packet`

- [ ] **Step 1: Add route and OpenAPI contract**

```python
if path == "/api/v1/commercial_purchase_approval_packets/latest":
    self._send(orchestrator.commercial_purchase_approval_packet_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 2: Add admin labels and summary tile**

Add `commercial_purchase_approval_packet_title`, `commercial_purchase_approval_ready`, `commercial_purchase_approval_ready_with_warnings`, and `commercial_purchase_approval_blocked` in English and Korean. Fetch the endpoint in the existing readiness grid.

- [ ] **Step 3: Run focused test**

Run: `python tests/test_commercial_purchase_approval_packet.py`
Expected: PASS.

### Task 3: Docs, Analytics, And Figma Records

**Files:**
- Create: `docs/commercial_purchase_approval_packet.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Produces: analytics metric `commercial_purchase_approval_warning_count`
- Produces: FigJam artifact note `KRW 2B Commercial Purchase Approval Packet`

- [ ] **Step 1: Update documentation**

Document `/api/v1/commercial_purchase_approval_packets/latest`, `local_commercial_purchase_approval_packet`, runtime shape, purchase approval status rules, Code Connect exclusion, review-process non-blocker policy, and single-product packaging decision.

- [ ] **Step 2: Update artifact tests**

Extend `tests/test_plugin_driven_artifacts.py` so docs and plans require the new endpoint, measurement status, metric, FigJam artifact, and verification command.

- [ ] **Step 3: Run docs/artifact test**

Run: `python tests/test_plugin_driven_artifacts.py`
Expected: PASS.

### Task 4: Verification And Commit

**Files:**
- Modify only files listed above.

**Interfaces:**
- Produces: pushed PR branch with commercial purchase approval packet runtime increment.

- [ ] **Step 1: Run verification**

Run:

```bash
python tests/test_commercial_purchase_approval_packet.py
python tests/test_commercial_proposal_packet.py
python tests/test_commercial_demo_scenarios.py
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
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_purchase_approval_packet.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-purchase-approval-packet-runtime.md tests/test_commercial_purchase_approval_packet.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial purchase approval packet runtime"
git push
```

