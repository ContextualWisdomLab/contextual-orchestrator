# Commercial Operations Readiness

Runtime endpoint: `/api/v1/commercial_operations_readiness/latest`.

This document defines the operations-handoff readiness gate for a
KRW 2,000,000,000 buyer handoff. It turns production operations gaps into
owners, actions, and exit criteria. It is not a valuation guarantee, purchase
commitment, legal opinion, or production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without a concrete failure are not blockers. Blockers
are concrete security failures, API contract failures, document contract
mismatches, reproducible product defects, or Code Connect usage.

Do not create a separate library, Git submodule, or extracted package now. Keep
Contextual Orchestrator as one enterprise control-plane product until a second
product, independent release cadence, or buyer security provenance requirement
creates an extraction trigger.

## Operations Inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Commercial onboarding readiness | `/api/v1/commercial_onboarding_readiness/latest` | Primary owner/action/exit-criteria source. |
| Commercial contract readiness | `/api/v1/commercial_contract_readiness/latest` | Support/SLO, legal, security, and buyer input source. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest`, `docs/analytics_spec.md` | Separates local measured metrics from production telemetry. |
| Acceptance check | `/api/v1/commercial_acceptance_checks/latest` | Buyer go/no-go and handoff exit criteria. |
| REST API design | `docs/rest_api_design.md` | Endpoint and operator API handoff source. |

## Runtime Shape

`/api/v1/commercial_operations_readiness/latest` returns:

- `operations_status`: `commercial_operations_ready`,
  `commercial_operations_ready_with_warnings`, or
  `commercial_operations_blocked`;
- `measurement_status`: `local_commercial_operations_readiness`;
- `operations_summary`: ready, warning, blocked, production-evidence action,
  and review-process blocker counts;
- `operations_items`: deployment runbook, monitoring/telemetry capture,
  incident/rollback plan, backup/recovery plan, support/SLO ownership,
  acceptance handoff, security/legal handoff, review-process policy, and
  packaging decision;
- `concrete_blockers`: only concrete product, security, API contract, document,
  or Code Connect failures;
- `operations_status_rules`: stable ready/warning/blocked rules;
- `related_runtime_reports`: onboarding, contract, procurement, gap-register,
  release-candidate, and acceptance context;
- `library_split_decision`: current single-product packaging decision;
- `plugin_traceability`: Figma, Product Design, Superpowers, Ponytail, and Data
  Analytics responsibilities;
- `operations_links`: editable Figma/FigJam links, endpoint, and documentation.

## Operations Status Rules

| Status | Rule |
| --- | --- |
| `commercial_operations_ready` | Deployment, monitoring, incident, backup, support, acceptance, security/legal, review, and packaging evidence are ready. |
| `commercial_operations_ready_with_warnings` | Local operations plan is ready while production telemetry, incident, backup, or SLO evidence remains explicit warnings. |
| `commercial_operations_blocked` | Missing operations packet evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks operations handoff. |

## KRW 2B Commercial Operations Readiness

The repository can package an operations-handoff plan without pretending that
production operations evidence already exists:

- deployment runbook ties the README, REST contract, onboarding plan, and
  operations handoff plan together;
- monitoring/telemetry capture records adoption, latency, verifier outcomes,
  trace completeness, support events, and deployment health only after a buyer
  environment exists;
- incident/rollback plan remains a production-input warning until the first
  drill and rollback record exist;
- backup/recovery plan remains a production-input warning until buyer topology,
  retention, and restore proof are known;
- support/SLO ownership carries forward from onboarding as an explicit warning;
- security/legal handoff and acceptance handoff are ready from local packet
  evidence;
- review-process delay remains non-blocking until a concrete failure appears;
- single-product packaging remains the default until a real extraction trigger
  exists.

## Plugin Traceability

| Plugin | Operations-readiness responsibility |
| --- | --- |
| Product Design | Keep operations evidence visible in the existing admin observability surface. |
| Figma | Record the editable FigJam flow named `KRW 2B Commercial Operations Readiness`. |
| Data Analytics | Separate local measured analytics from production operations telemetry. |
| Superpowers | Maintain the implementation plan, acceptance checks, and concrete blocker rules. |
| Ponytail | Keep one deployable product and avoid package extraction before a trigger. |

## Verification

```bash
python tests/test_commercial_operations_readiness.py
python tests/test_commercial_onboarding_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
pytest -q
```
