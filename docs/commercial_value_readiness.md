# Commercial Value Readiness

Runtime endpoint: `/api/v1/commercial_value_readiness/latest`.

This document defines the buyer economic-review readiness gate for a
KRW 2,000,000,000 buyer packet. It separates repo-local measured evidence from
buyer-specific ROI inputs, reference proof, budget-owner evidence, and payback
assumptions. It is not a valuation guarantee, purchase commitment, revenue
proof, financial advice, or production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without a concrete failure are not blockers. Blockers
are concrete security failures, API contract failures, document contract
mismatches, reproducible product defects, or Code Connect usage.

Do not create a separate library, Git submodule, or extracted package now. Keep
Contextual Orchestrator as one enterprise control-plane product until a second
product, independent release cadence, or buyer security provenance requirement
creates an extraction trigger.

## Value Readiness Inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Commercial readiness | `/api/v1/commercial_readiness/latest` | Primary local value-case and target contract review source. |
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Portable buyer evidence source. |
| Commercial security attestation | `/api/v1/commercial_security_attestations/latest` | Security and buyer trust gate source. |
| Local analytics snapshot | `/api/v1/analytics_snapshots/latest`, `docs/analytics_spec.md` | Separates measured local evidence from buyer-specific production metrics. |
| Commercial procurement readiness | `/api/v1/commercial_procurement_readiness/latest` | Budget, procurement, ROI, legal, and support input context. |

## Runtime Shape

`/api/v1/commercial_value_readiness/latest` returns:

- `value_status`: `commercial_value_ready`,
  `commercial_value_ready_with_warnings`, or `commercial_value_blocked`;
- `measurement_status`: `local_commercial_value_readiness`;
- `value_summary`: ready, warning, blocked, buyer-financial gap,
  external-value-proof gap, and review-process blocker counts;
- `value_items`: commercial value-case basis, local analytics evidence, buyer
  evidence export, pricing/package rationale, ROI model inputs, reference
  customer or case-study proof, procurement budget owner, implementation
  payback assumption, review-process policy, and packaging decision;
- `concrete_blockers`: only concrete product, security, API contract, document,
  or Code Connect failures;
- `value_status_rules`: stable ready/warning/blocked rules;
- `related_runtime_reports`: security attestation, export, commercial,
  operations, onboarding, contract, procurement, gap-register, release-candidate,
  and acceptance context;
- `library_split_decision`: current single-product packaging decision;
- `plugin_traceability`: Figma, Product Design, Superpowers, Ponytail, and Data
  Analytics responsibilities;
- `value_links`: editable Figma/FigJam links, endpoint, and documentation.

## Value Status Rules

| Status | Rule |
| --- | --- |
| `commercial_value_ready` | Commercial value case, local analytics, evidence export, pricing rationale, ROI inputs, reference proof, budget owner, payback assumptions, review policy, and packaging evidence are ready. |
| `commercial_value_ready_with_warnings` | Repo-local value evidence is ready while buyer ROI inputs, reference proof, budget owner, or payback assumptions remain explicit warnings. |
| `commercial_value_blocked` | Missing local value packet evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks value readiness. |

## KRW 2B Commercial Value Readiness

The repository can package an economic-review packet without pretending buyer
ROI evidence already exists:

- commercial value-case basis keeps the KRW 2,000,000,000 target tied to API
  compatibility, evidence control plane, replay, and audit controls;
- local analytics evidence uses measured prototype signals only, such as
  compatible API adoption, trace-complete workflow rate, policy-safe routing
  rate, and provider exclusion miss rate;
- buyer evidence export and security attestation provide trust context for the
  value packet;
- pricing/package rationale remains tied to documented product capabilities,
  not a guaranteed valuation;
- ROI model inputs remain buyer-financial-input warnings until baseline cost,
  workflow volume, rework cost, compliance cost, and time-saving assumptions are
  supplied;
- reference customer or case-study proof remains an external-value-proof warning
  until the buyer accepts reference, paid-pilot, or waiver evidence;
- procurement budget owner remains a buyer-financial-input warning until buyer
  sponsor, budget owner, approval path, and order-form authority are known;
- implementation payback assumption remains a buyer-financial-input warning
  until deployment scope, staffing, and payback window are accepted;
- review-process delay remains non-blocking until a concrete failure appears;
- single-product packaging remains the default until a real extraction trigger
  exists.

## Plugin Traceability

| Plugin | Value-readiness responsibility |
| --- | --- |
| Product Design | Keep value readiness visible in the existing admin observability surface. |
| Figma | Record the editable FigJam flow named `KRW 2B Commercial Value Readiness`. |
| Data Analytics | Separate local measured analytics from buyer-specific ROI and proof inputs. |
| Superpowers | Maintain the implementation plan, acceptance checks, and concrete blocker rules. |
| Ponytail | Keep one deployable product and avoid package extraction before a trigger. |

## Verification

```bash
python tests/test_commercial_value_readiness.py
python tests/test_commercial_security_attestation.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
pytest -q
```
