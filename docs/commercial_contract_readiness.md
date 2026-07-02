# Commercial Contract Readiness

Runtime endpoint: `/api/v1/commercial_contract_readiness/latest`.

This document defines the contract-readiness gate for a KRW 2,000,000,000
buyer legal and procurement review. It is a local product evidence gate, not a
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

## Contract Inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Commercial procurement readiness | `/api/v1/commercial_procurement_readiness/latest` | Primary local procurement/legal packet source. |
| Commercial gap register | `/api/v1/commercial_gap_registers/latest` | Production support/SLO and buyer-specific input source. |
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Buyer-readable audit/export obligation source. |
| Saleability decision | `/api/v1/saleability_decisions/latest` | Concrete blocker and warning policy source. |
| Security metadata | `SECURITY.md`, `requirements.lock`, security workflows | Security and privacy term source. |
| License metadata | `LICENSE`, `pyproject.toml` | Rights and commercial packaging source. |

## Runtime Shape

`/api/v1/commercial_contract_readiness/latest` returns:

- `contract_status`: `commercial_contract_ready`,
  `commercial_contract_ready_with_warnings`, or
  `commercial_contract_blocked`;
- `measurement_status`: `local_commercial_contract_readiness`;
- `contract_summary`: ready, warning, blocked, support/SLO gap, buyer
  order-form gap, and review-process blocker counts;
- `contract_items`: term rows for license/commercial rights, security/privacy,
  audit/export obligations, contract packet docs, support/SLO terms, buyer
  order-form input, review-process policy, and packaging decision;
- `concrete_blockers`: only concrete product, security, API contract, document,
  or Code Connect failures;
- `contract_status_rules`: stable ready/warning/blocked rules;
- `related_runtime_reports`: procurement, gap-register, release-candidate, and
  acceptance context;
- `library_split_decision`: current single-product packaging decision;
- `plugin_traceability`: Figma, Product Design, Superpowers, Ponytail, and Data
  Analytics responsibilities;
- `contract_links`: editable Figma/FigJam links, endpoint, and documentation.

## Contract Status Rules

| Status | Rule |
| --- | --- |
| `commercial_contract_ready` | License, security/privacy, audit/export, support/SLO, buyer order-form, review, and packaging terms are ready. |
| `commercial_contract_ready_with_warnings` | Local contract packet is ready while production support/SLO or buyer order-form inputs remain explicit warnings. |
| `commercial_contract_blocked` | Missing contract packet evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks contract readiness. |

## KRW 2B Commercial Contract Readiness

The local repository can package contract-readiness evidence for buyer legal and
procurement diligence:

- license/commercial-rights evidence from `LICENSE` and `pyproject.toml`;
- security/privacy evidence from `SECURITY.md`, locked dependencies, security
  workflows, and runtime readiness profile;
- audit/export evidence from the commercial evidence export endpoint and REST
  contract;
- support/SLO terms as explicit production-input warnings until a customer
  environment exists;
- buyer order-form input as an explicit buyer-specific warning until a named
  buyer supplies order-form, ROI, legal, support, and deployment inputs;
- review-process delay as non-blocking until it produces a concrete failure;
- single-product packaging as the default until a real extraction trigger
  exists.

## Plugin Traceability

| Plugin | Contract-readiness responsibility |
| --- | --- |
| Product Design | Keep legal/procurement evidence visible in the existing admin observability surface. |
| Figma | Record the editable FigJam flow named `KRW 2B Commercial Contract Readiness`. |
| Data Analytics | Separate measured local evidence from proposed production or buyer-specific terms. |
| Superpowers | Maintain the implementation plan, acceptance checks, and concrete blocker rules. |
| Ponytail | Keep the smallest artifact set and avoid library/submodule/package extraction before a trigger. |

## Verification

```bash
python tests/test_commercial_contract_readiness.py
python tests/test_commercial_procurement_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
pytest -q
```
