# Commercial Due Diligence Room Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a KRW 2,000,000,000 commercial due diligence room runtime packet that packages existing buyer approval and evidence reports into one admin-only buyer review artifact.

**Architecture:** Reuse the current stdlib `TaskOrchestrator` commercial report pattern. Add one aggregate method, one admin-only HTTP route, one OpenAPI path, one admin readiness card, one focused test file, and matching docs. Keep the product as one enterprise control plane; do not extract a library, submodule, or package.

**Tech Stack:** Python stdlib HTTP server, in-memory `TaskOrchestrator`, embedded admin HTML/JS, repository markdown docs, assert-based focused tests, pytest.

## Global Constraints

- No new repo dependencies.
- Figma Code Connect must not be used.
- Review process delay is not a blocker; only concrete CI, security, API, runtime, doc, or product defects are blockers.
- Buyer authority documents, production telemetry, hosted scan evidence, and third-party attestations must stay `proposed_until_buyer_specific`.
- Measured local evidence must remain separate from proposed production or buyer-specific metrics.
- Keep `Contextual Orchestrator` as one deployable enterprise control-plane product.

---

### Task 1: Focused Runtime Contract

**Files:**
- Create: `tests/test_commercial_due_diligence_room.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_due_diligence_room_report(target_contract_value_krw, locale_bundles, security_profile)`.
- Produces: Focused expectations for `due_diligence_status`, `measurement_status`, `diligence_summary`, `diligence_sections`, `buyer_missing_artifacts`, admin-only endpoint auth, OpenAPI path, admin translations, and docs.

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_due_diligence_room_report(
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
assert report["due_diligence_status"] == "commercial_due_diligence_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_due_diligence_room"
assert report["diligence_summary"]["warning_count"] == 2
assert report["diligence_summary"]["blocked_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_commercial_due_diligence_room.py`

Expected: FAIL with `AttributeError: 'TaskOrchestrator' object has no attribute 'commercial_due_diligence_room_report'`.

### Task 2: Runtime, HTTP, OpenAPI, And Admin Surface

**Files:**
- Modify: `contextual_orchestrator/orchestrator.py`
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: existing commercial reports: purchase approval, proposal, completion, demo, buyer acceptance workflow, close, procurement, contract, value, security, onboarding, operations, analytics snapshot, and admin state.
- Produces: `TaskOrchestrator.commercial_due_diligence_room_report()`, `GET /api/v1/commercial_due_diligence_rooms/latest`, OpenAPI `operationId=get_latest_commercial_due_diligence_room`, and admin readiness card keys.

- [ ] **Step 1: Implement report method**

```python
def commercial_due_diligence_room_report(
    self,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    purchase = self.commercial_purchase_approval_packet_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = self.admin_state()
    return {
        "due_diligence_status": "commercial_due_diligence_ready_with_warnings",
        "measurement_status": "local_commercial_due_diligence_room",
        "diligence_summary": {
            "section_count": 10,
            "ready_count": 8,
            "warning_count": 2,
            "blocked_count": 0,
            "review_process_is_blocker": purchase["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "buyer_missing_artifacts": [
            "named buyer signer",
            "budget owner and purchase order",
            "buyer DPA or privacy acceptance",
            "production telemetry",
            "third-party security attestation",
        ],
    }
```

- [ ] **Step 2: Add HTTP route**

```python
if path == "/api/v1/commercial_due_diligence_rooms/latest":
    self._send(orchestrator.commercial_due_diligence_room_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 3: Add OpenAPI path**

```python
"/api/v1/commercial_due_diligence_rooms/latest": {
    "get": {
        "operationId": "get_latest_commercial_due_diligence_room",
        "summary": "Get KRW 2B commercial due diligence room",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial due diligence room"}},
    }
}
```

- [ ] **Step 4: Add admin card**

```javascript
const dueDiligenceStatus = commercialDueDiligence.due_diligence_status || "commercial_due_diligence_blocked";
const dueDiligenceStatusClass = dueDiligenceStatus === "commercial_due_diligence_ready" ? "green" : dueDiligenceStatus === "commercial_due_diligence_ready_with_warnings" ? "amber" : "red";
```

- [ ] **Step 5: Run focused test**

Run: `python tests/test_commercial_due_diligence_room.py`

Expected: PASS and prints `ok`.

### Task 3: Durable Docs And Metric Contract

**Files:**
- Create: `docs/commercial_due_diligence_room.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: runtime endpoint name and report keys from Task 2.
- Produces: durable buyer diligence docs, analytics metric definition, and artifact tests.

- [ ] **Step 1: Document runtime shape**

```md
# Commercial Due Diligence Room

Runtime endpoint: `/api/v1/commercial_due_diligence_rooms/latest`.

`TaskOrchestrator.commercial_due_diligence_room_report()` returns:

- `due_diligence_status`
- `measurement_status`: `local_commercial_due_diligence_room`
- `diligence_sections`
- `buyer_missing_artifacts`
- `related_runtime_reports`
```

- [ ] **Step 2: Add analytics metric**

```md
| `commercial_due_diligence_warning_count` | Count of warning sections in the buyer due diligence room, with buyer authority documents, production telemetry, hosted scan evidence, and third-party attestations kept separate from measured local diligence evidence. | proposed_until_buyer_specific | `/api/v1/commercial_due_diligence_rooms/latest` response. |
```

- [ ] **Step 3: Add artifact test**

```python
def test_commercial_due_diligence_room_defines_buyer_diligence_room() -> None:
    diligence = read_text("docs/commercial_due_diligence_room.md")
    assert "Commercial Due Diligence Room" in diligence
    assert "Runtime endpoint: `/api/v1/commercial_due_diligence_rooms/latest`" in diligence
    assert "local_commercial_due_diligence_room" in diligence
```

- [ ] **Step 4: Run docs test**

Run: `python tests/test_plugin_driven_artifacts.py`

Expected: PASS and prints `ok`.

### Task 4: Verification, FigJam, Commit, And PR Check

**Files:**
- Modify only files from Tasks 1-3.

**Interfaces:**
- Consumes: implemented runtime endpoint, docs, tests, and Figma diagram skill.
- Produces: FigJam `KRW 2B Commercial Due Diligence Room`, committed branch, pushed PR, and PR status evidence.

- [ ] **Step 1: Generate FigJam diagram**

Use `generate_diagram` with title `KRW 2B Commercial Due Diligence Room`. Mermaid must avoid Code Connect references as a tool and include the endpoint `/api/v1/commercial_due_diligence_rooms/latest`.

- [ ] **Step 2: Run verification**

```bash
python tests/test_commercial_due_diligence_room.py
python tests/test_commercial_purchase_approval_packet.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
git diff --check
pytest -q
```

Expected: focused tests print `ok`, compileall and diff check exit 0, and pytest passes.

- [ ] **Step 3: Commit and push**

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_due_diligence_room.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-due-diligence-room-runtime.md tests/test_commercial_due_diligence_room.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial due diligence room runtime"
git push
```

- [ ] **Step 4: Check PR status**

```bash
gh pr view 14 --json url,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
gh pr checks 14
```

Expected: current head is pushed. Queued review or model-review delay is not a blocker unless a concrete failing check appears.
