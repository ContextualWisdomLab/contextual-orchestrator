# Commercial Mutual Action Plan

This document defines the KRW 2,000,000,000 buyer/seller mutual action plan for
Contextual Orchestrator.

Runtime endpoint: `/api/v1/commercial_mutual_action_plans/latest`.

The mutual action plan turns the commercial saleability gate into named
milestones, owners, exit criteria, source evidence, and next actions for a buyer
close path. It is a final execution layer in one enterprise orchestration
control plane, not a separate product.

Figma Code Connect is not used.

Review process is not a blocker. Review bot delay, reviewer delay, queued model
review, or pending review process without a concrete failure is tracked as
process latency, not product incompleteness.

Do not create a separate library, Git submodule, or extracted package now. Keep
one enterprise orchestration control plane until there is repo-local evidence
for a second product, independent release cadence, or buyer security provenance
requirement.

## Action Plan Inputs

| Input | Runtime or document | Purpose |
|---|---|---|
| Commercial saleability gate | `/api/v1/commercial_saleability_gates/latest` | Final commercial go/no-go state and blocker policy. |
| Investment committee memo | `/api/v1/commercial_investment_committee_memos/latest` | Executive recommendation and committee approval conditions. |
| Close readiness | `/api/v1/commercial_close_readiness/latest` | Signature, budget, security acceptance, and go-live conditions. |
| Legal and procurement readiness | `/api/v1/commercial_contract_readiness/latest`, `/api/v1/commercial_procurement_readiness/latest` | Contract, procurement, and order-form path. |
| Implementation readiness | `/api/v1/commercial_onboarding_readiness/latest`, `/api/v1/commercial_operations_readiness/latest` | Paid onboarding, operations, SLO, support, and handoff readiness. |
| Value and security readiness | `/api/v1/commercial_value_readiness/latest`, `/api/v1/commercial_security_attestations/latest` | Economic review and local security evidence with external caveats. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest` | Local measured metric provenance. |
| Figma artifacts | `docs/figma_artifacts.md` | Editable stakeholder flow record without Code Connect. |

## Runtime Shape

`/api/v1/commercial_mutual_action_plans/latest` returns:

- `mutual_action_plan_status`: `commercial_mutual_action_plan_ready`,
  `commercial_mutual_action_plan_ready_with_warnings`, or
  `commercial_mutual_action_plan_blocked`;
- `target_contract_value_krw` and `target_contract_value_display`;
- `measurement_status`: `local_commercial_mutual_action_plan`;
- `source_note`: local evidence caveat and non-guarantee statement;
- `go_no_go_recommendation`: execute, execute-with-conditions, or blocked
  recommendation;
- `plan_summary`: milestone count, ready count, warning count, blocker count,
  endpoint count, review-process policy, and Code Connect exclusion;
- `milestones`: owner-scoped buyer/seller milestones;
- `required_runtime_endpoints`: endpoint chain needed for execution review;
- `buyer_seller_owners`: buyer and seller owner lists;
- `exit_criteria`: final completion criteria for MAP execution;
- `buyer_authority_gaps`: buyer authority artifacts still required;
- `production_external_evidence_gaps`: production and third-party evidence still
  required;
- `metric_provenance`: measured local sources separated from proposed buyer,
  production, or third-party inputs;
- `operator_next_actions`: next concrete operator steps;
- `concrete_blockers`: concrete defects that block MAP execution;
- `review_process_policy`: review-process non-blocker definition;
- `library_split_decision`: single-product packaging decision;
- `plugin_traceability`: Product Design, Figma, Superpowers, Ponytail, and Data
  Analytics traceability;
- `plan_links`: Figma, FigJam, runtime endpoint, and documentation links.

## Action Plan Status Rules

| Status | Rule |
|---|---|
| `commercial_mutual_action_plan_ready` | All milestones are ready and no buyer authority, production, or third-party evidence remains open. |
| `commercial_mutual_action_plan_ready_with_warnings` | Measured local saleability, committee, close, legal, procurement, onboarding, operations, security, and analytics evidence are ready while buyer authority or production/external evidence remains an explicit warning. |
| `commercial_mutual_action_plan_blocked` | Security failure, API contract regression, document mismatch, runtime defect, missing local saleability evidence, or Code Connect usage blocks MAP execution. |

## Metric Provenance

Measured local sources:

- `/api/v1/commercial_saleability_gates/latest`
- `/api/v1/commercial_investment_committee_memos/latest`
- `/api/v1/analytics_snapshots/latest`

Proposed or buyer-specific sources:

- buyer authority confirmation;
- production telemetry;
- third-party security attestation;
- support SLO acceptance.

## KRW 2B Commercial Mutual Action Plan

The KRW 2B Commercial Mutual Action Plan is complete when:

- `/api/v1/commercial_mutual_action_plans/latest` returns
  `local_commercial_mutual_action_plan`;
- no concrete product, API, security, runtime, or document blocker remains;
- buyer final authority is supplied or explicitly waived;
- production telemetry and third-party evidence plan is accepted;
- admin readiness, OpenAPI, README, REST API docs, analytics spec, Figma
  artifact record, Superpowers plan, and tests all reference the same endpoint;
- Figma Code Connect remains unused.
