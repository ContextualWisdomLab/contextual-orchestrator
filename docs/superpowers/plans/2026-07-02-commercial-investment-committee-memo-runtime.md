# Commercial Investment Committee Memo Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `commercial_investment_committee_memo_report()` and `/api/v1/commercial_investment_committee_memos/latest` so the KRW 2,000,000,000 investment committee memo is available as runtime evidence.

**Architecture:** Reuse the current stdlib `TaskOrchestrator` commercial report pattern. Aggregate the due diligence room, purchase approval packet, proposal packet, completion scorecard, demo scenarios, buyer acceptance workflow, close/procurement/contract/value/security/onboarding/operations readiness, analytics snapshot, and admin state into one memo payload. Keep the product as one enterprise control plane; do not extract a library, submodule, or package.

**Tech Stack:** Python stdlib HTTP server, in-memory `TaskOrchestrator`, embedded admin HTML/JS, repository markdown docs, assert-based focused tests, pytest.

## Global Constraints

- No new repo dependencies.
- Figma Code Connect must not be used.
- Review process delay is not a blocker; only concrete CI, security, API, runtime, doc, or product defects are blockers.
- Buyer final authority, production telemetry, hosted scan evidence, and external attestations must stay `proposed_until_buyer_specific`.
- Measured local evidence must remain separate from proposed production or buyer-specific metrics.
- Keep `Contextual Orchestrator` as one deployable enterprise control-plane product.

---

### Task 1: Focused Runtime Contract

**Files:**
- Create: `tests/test_commercial_investment_committee_memo.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.commercial_investment_committee_memo_report(target_contract_value_krw, locale_bundles, security_profile)`.
- Produces: Focused expectations for `investment_committee_status`, `measurement_status`, `executive_recommendation`, `memo_summary`, `memo_sections`, `committee_decision_questions`, admin-only endpoint auth, OpenAPI path, admin translations, and docs.

- [ ] **Step 1: Write the failing test**

```python
report = orchestrator.commercial_investment_committee_memo_report(
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
assert report["investment_committee_status"] == "commercial_investment_committee_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_investment_committee_memo"
assert report["memo_summary"]["warning_count"] == 2
assert report["memo_summary"]["blocked_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_commercial_investment_committee_memo.py`

Expected: FAIL with `AttributeError: 'TaskOrchestrator' object has no attribute 'commercial_investment_committee_memo_report'`.

### Task 2: Runtime, HTTP, OpenAPI, And Admin Surface

**Files:**
- Modify: `contextual_orchestrator/orchestrator.py`
- Modify: `contextual_orchestrator/server.py`
- Modify: `contextual_orchestrator/api_contract.py`
- Modify: `contextual_orchestrator/admin.py`

**Interfaces:**
- Consumes: `commercial_due_diligence_room_report(...) -> dict[str, Any]` and earlier commercial reports.
- Produces: `TaskOrchestrator.commercial_investment_committee_memo_report(...) -> dict[str, Any]`, `GET /api/v1/commercial_investment_committee_memos/latest`, OpenAPI `operationId=get_latest_commercial_investment_committee_memo`, and admin readiness card keys.

- [ ] **Step 1: Implement report method**

```python
def commercial_investment_committee_memo_report(
    self,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    due_diligence = self.commercial_due_diligence_room_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    return {
        "investment_committee_status": "commercial_investment_committee_ready_with_warnings",
        "measurement_status": "local_commercial_investment_committee_memo",
        "executive_recommendation": {
            "recommendation_status": "recommend_with_buyer_conditions",
        },
        "memo_summary": {
            "section_count": 10,
            "ready_count": 8,
            "warning_count": 2,
            "blocked_count": 0,
            "review_process_is_blocker": due_diligence["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
    }
```

- [ ] **Step 2: Add HTTP route**

```python
if path == "/api/v1/commercial_investment_committee_memos/latest":
    self._send(orchestrator.commercial_investment_committee_memo_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security.readiness_profile(),
    ))
    return
```

- [ ] **Step 3: Add OpenAPI path**

```python
"/api/v1/commercial_investment_committee_memos/latest": {
    "get": {
        "operationId": "get_latest_commercial_investment_committee_memo",
        "summary": "Get KRW 2B commercial investment committee memo",
        "security": [{"admin_bearer_auth": []}],
        "responses": {"200": {"description": "Commercial investment committee memo"}},
    }
}
```

- [ ] **Step 4: Add admin card**

```javascript
const investmentCommitteeStatus = commercialInvestmentCommittee.investment_committee_status || "commercial_investment_committee_blocked";
const investmentCommitteeStatusClass = investmentCommitteeStatus === "commercial_investment_committee_ready" ? "green" : investmentCommitteeStatus === "commercial_investment_committee_ready_with_warnings" ? "amber" : "red";
```

- [ ] **Step 5: Run focused test**

Run: `python tests/test_commercial_investment_committee_memo.py`

Expected: PASS and prints `ok`.

### Task 3: Durable Docs And Metric Contract

**Files:**
- Create: `docs/commercial_investment_committee_memo.md`
- Modify: `README.md`
- Modify: `docs/rest_api_design.md`
- Modify: `docs/analytics_spec.md`
- Modify: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: runtime endpoint name and report keys from Task 2.
- Produces: durable investment committee memo docs, analytics metric definition, and artifact tests.

- [ ] **Step 1: Document runtime shape**

```md
# Commercial Investment Committee Memo

Runtime endpoint: `/api/v1/commercial_investment_committee_memos/latest`.

`TaskOrchestrator.commercial_investment_committee_memo_report()` returns:

- `investment_committee_status`
- `measurement_status`: `local_commercial_investment_committee_memo`
- `executive_recommendation`
- `memo_sections`
- `committee_decision_questions`
```

- [ ] **Step 2: Add analytics metric**

```md
| `commercial_investment_committee_warning_count` | Count of warning sections in the investment committee memo, with buyer final authority, production telemetry, hosted scan evidence, and external attestations kept separate from measured local committee evidence. | proposed_until_buyer_specific | `/api/v1/commercial_investment_committee_memos/latest` response. |
```

- [ ] **Step 3: Add artifact test**

```python
def test_commercial_investment_committee_memo_defines_executive_decision_packet() -> None:
    memo = read_text("docs/commercial_investment_committee_memo.md")
    assert "Commercial Investment Committee Memo" in memo
    assert "Runtime endpoint: `/api/v1/commercial_investment_committee_memos/latest`" in memo
    assert "local_commercial_investment_committee_memo" in memo
```

- [ ] **Step 4: Run docs test**

Run: `python tests/test_plugin_driven_artifacts.py`

Expected: PASS and prints `ok`.

### Task 4: Verification, FigJam, Commit, And PR Check

**Files:**
- Modify only files from Tasks 1-3.

**Interfaces:**
- Consumes: implemented runtime endpoint, docs, tests, and Figma diagram skill.
- Produces: FigJam `KRW 2B Commercial Investment Committee Memo`, committed branch, pushed PR, and PR status evidence.

- [ ] **Step 1: Generate FigJam diagram**

Use `generate_diagram` with title `KRW 2B Commercial Investment Committee Memo`. Mermaid must avoid Code Connect references as a tool and include the endpoint `/api/v1/commercial_investment_committee_memos/latest`.

- [ ] **Step 2: Run verification**

```bash
python tests/test_commercial_investment_committee_memo.py
python tests/test_commercial_due_diligence_room.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
git diff --check
pytest -q
```

Expected: focused tests print `ok`, compileall and diff check exit 0, and pytest passes.

- [ ] **Step 3: Commit and push**

```bash
git add README.md contextual_orchestrator/admin.py contextual_orchestrator/api_contract.py contextual_orchestrator/orchestrator.py contextual_orchestrator/server.py docs/analytics_spec.md docs/commercial_investment_committee_memo.md docs/figma_artifacts.md docs/rest_api_design.md docs/superpowers/plans/2026-07-02-commercial-investment-committee-memo-runtime.md tests/test_commercial_investment_committee_memo.py tests/test_plugin_driven_artifacts.py
git commit -m "feat: add commercial investment committee memo runtime"
git push
```

- [ ] **Step 4: Check PR status**

```bash
gh pr view 14 --json url,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
gh pr checks 14
```

Expected: current head is pushed. Queued review or model-review delay is not a blocker unless a concrete failing check appears.
