# Commercial Onboarding Readiness

Runtime endpoint: `/api/v1/commercial_onboarding_readiness/latest`.

This document defines the paid-onboarding readiness gate for a
KRW 2,000,000,000 buyer close. It turns the remaining production and
buyer-specific warnings into owners, actions, and exit criteria. It is not a
valuation guarantee, purchase commitment, legal opinion, or production
compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without a concrete failure are not blockers. Blockers
are concrete security failures, API contract failures, document contract
mismatches, reproducible product defects, or Code Connect usage.

Do not create a separate library, Git submodule, or extracted package now. Keep
Contextual Orchestrator as one enterprise control-plane product until a second
product, independent release cadence, or buyer security provenance requirement
creates an extraction trigger.

## Onboarding Inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Commercial contract readiness | `/api/v1/commercial_contract_readiness/latest` | Primary contract and buyer-warning source. |
| Commercial procurement readiness | `/api/v1/commercial_procurement_readiness/latest` | Procurement packet and source-gap context. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest`, `docs/analytics_spec.md` | Separates local measured metrics from production onboarding telemetry. |
| Acceptance check | `/api/v1/commercial_acceptance_checks/latest` | Buyer go/no-go and exit-criteria source. |
| Security policy | `SECURITY.md` | Security/legal handoff source. |

## Runtime Shape

`/api/v1/commercial_onboarding_readiness/latest` returns:

- `onboarding_status`: `commercial_onboarding_ready`,
  `commercial_onboarding_ready_with_warnings`, or
  `commercial_onboarding_blocked`;
- `measurement_status`: `local_commercial_onboarding_readiness`;
- `onboarding_summary`: ready, warning, blocked, support/SLO action,
  buyer-input action, and review-process blocker counts;
- `onboarding_items`: buyer kickoff packet, support/SLO kickoff, buyer
  order-form kickoff, telemetry capture plan, acceptance exit criteria,
  security/legal handoff, review-process policy, and packaging decision;
- `concrete_blockers`: only concrete product, security, API contract, document,
  or Code Connect failures;
- `onboarding_status_rules`: stable ready/warning/blocked rules;
- `related_runtime_reports`: contract, procurement, gap-register,
  release-candidate, and acceptance context;
- `library_split_decision`: current single-product packaging decision;
- `plugin_traceability`: Figma, Product Design, Superpowers, Ponytail, and Data
  Analytics responsibilities;
- `onboarding_links`: editable Figma/FigJam links, endpoint, and documentation.

## Onboarding Status Rules

| Status | Rule |
| --- | --- |
| `commercial_onboarding_ready` | Kickoff packet, support/SLO, buyer input, telemetry, acceptance, security/legal, review, and packaging actions are ready. |
| `commercial_onboarding_ready_with_warnings` | Local onboarding plan is ready while production support/SLO or buyer order-form actions remain explicit warnings. |
| `commercial_onboarding_blocked` | Missing onboarding packet evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks onboarding. |

## KRW 2B Commercial Onboarding Readiness

The repository can package a paid-onboarding plan without pretending that
production or buyer-specific evidence already exists:

- buyer kickoff packet ties the product overview to contract readiness and
  onboarding actions;
- support/SLO kickoff captures support owner, escalation path, response target,
  and incident drill evidence during onboarding;
- buyer order-form kickoff captures order form, ROI, legal questionnaire,
  deployment, and support inputs;
- telemetry capture plan keeps production telemetry separate from local
  prototype metrics;
- acceptance exit criteria use the commercial acceptance check and buyer
  acceptance runbook;
- review-process delay remains non-blocking until a concrete failure appears;
- single-product packaging remains the default until a real extraction trigger
  exists.

## Plugin Traceability

| Plugin | Onboarding-readiness responsibility |
| --- | --- |
| Product Design | Keep onboarding evidence visible in the existing admin observability surface. |
| Figma | Record the editable FigJam flow named `KRW 2B Commercial Onboarding Readiness`. |
| Data Analytics | Separate local measured analytics from production onboarding telemetry. |
| Superpowers | Maintain the implementation plan, acceptance checks, and concrete blocker rules. |
| Ponytail | Keep one deployable product and avoid package extraction before a trigger. |

## Verification

```bash
python tests/test_commercial_onboarding_readiness.py
python tests/test_commercial_contract_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
pytest -q
```
