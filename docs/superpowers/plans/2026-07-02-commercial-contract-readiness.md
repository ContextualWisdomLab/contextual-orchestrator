# Commercial Contract Readiness Implementation Plan

## Goal

Add `commercial_contract_readiness_report()` and
`/api/v1/commercial_contract_readiness/latest` so KRW 2,000,000,000 buyer legal
and procurement diligence can review support/SLO terms, security/privacy terms,
audit/export obligations, license/commercial rights, buyer order-form inputs,
review-process blocker policy, and packaging decision from one local runtime
gate.

## Architecture

Keep one repository and one deployable enterprise control plane. Add a thin
`TaskOrchestrator.commercial_contract_readiness_report()` wrapper over
`commercial_procurement_readiness_report()`, then expose it through
`/api/v1/commercial_contract_readiness/latest`, admin observability, OpenAPI,
Markdown docs, FigJam traceability, and focused tests.

No new repo dependencies.

Do not create a separate library, Git submodule, or extracted package now.

Figma Code Connect is not used.

Review process is not a blocker. Only concrete product defects, security
failures, API contract failures, document contract mismatches, or Code Connect
usage block the goal.

## Step 1: Focused Failing Test

Create `tests/test_commercial_contract_readiness.py` with assertions for:

```python
report = orchestrator.commercial_contract_readiness_report(...)
assert report["contract_status"] == "commercial_contract_ready_with_warnings"
assert report["measurement_status"] == "local_commercial_contract_readiness"
assert report["contract_summary"]["blocked_count"] == 0
assert report["contract_summary"]["warning_count"] == 2
assert report["contract_items"]
assert report["contract_links"]["runtime_endpoint"] == "/api/v1/commercial_contract_readiness/latest"
```

Also assert OpenAPI, admin translations, docs, authorization, and server
response shape.

Run:

```bash
python tests/test_commercial_contract_readiness.py
```

Expected: failure because `commercial_contract_readiness_report` is not defined.

## Step 2: Runtime Report

Add `commercial_contract_readiness_report(...)` to
`contextual_orchestrator/orchestrator.py`. Reuse
`commercial_procurement_readiness_report(...)`. Return `contract_status`,
`measurement_status`, `contract_summary`, `contract_items`,
`concrete_blockers`, `contract_status_rules`, `review_process_policy`,
`related_runtime_reports`, `library_split_decision`, `plugin_traceability`, and
`contract_links`.

Required contract items:

- `license_commercial_rights`
- `security_privacy_terms`
- `audit_export_obligations`
- `contract_packet_docs`
- `support_slo_terms`
- `buyer_order_form_input`
- `review_process_policy`
- `packaging_decision`

Run:

```bash
python tests/test_commercial_contract_readiness.py
```

Expected: report assertions pass once endpoint/docs/admin are connected.

## Step 3: Endpoint And Admin

Expose:

```text
GET /api/v1/commercial_contract_readiness/latest
operationId: get_latest_commercial_contract_readiness
```

Admin additions:

- `commercial_contract_readiness_title`
- `commercial_contract_ready`
- `commercial_contract_ready_with_warnings`
- `commercial_contract_blocked`
- fetch `/api/v1/commercial_contract_readiness/latest`
- show the status chip and add `contract warning/blocked` to readiness summary

Run:

```bash
python tests/test_commercial_contract_readiness.py
python tests/test_api_contract.py
```

## Step 4: Documentation And FigJam

Create `docs/commercial_contract_readiness.md` with the stable phrases:

- `Commercial Contract Readiness`
- `KRW 2,000,000,000`
- `Figma Code Connect is not used`
- `Review process is not a blocker`
- `Do not create a separate library, Git submodule, or extracted package now`
- `Contract Inputs`
- `Runtime Shape`
- `Contract Status Rules`
- `KRW 2B Commercial Contract Readiness`
- `/api/v1/commercial_contract_readiness/latest`
- `local_commercial_contract_readiness`

Record FigJam:

- `KRW 2B Commercial Contract Readiness`

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

## Step 5: Final Verification

Run:

```bash
python tests/test_commercial_contract_readiness.py
python tests/test_commercial_procurement_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Acceptance:

- contract readiness is admin-auth protected;
- warnings are explicit for production support/SLO and buyer order-form inputs;
- review-process delay is not a blocker;
- Code Connect remains unused;
- no new dependency or framework migration is introduced;
- package extraction remains deferred until an actual extraction trigger exists.
