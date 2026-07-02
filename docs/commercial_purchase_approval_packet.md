# Commercial Purchase Approval Packet

Runtime endpoint: `/api/v1/commercial_purchase_approval_packets/latest`.

This document defines the KRW 2,000,000,000 buyer purchase approval packet for
Contextual Orchestrator as one enterprise orchestration control plane. The
packet packages proposal, close, procurement, contract, value, security,
onboarding, operations, analytics, Figma, review-policy, and packaging evidence
into buyer-side approval gates for finance, procurement, legal, security, and
implementation owners.

It is not a valuation guarantee, purchase commitment, signed order, legal
opinion, production compliance certificate, or revenue proof. Figma Code Connect is not used.
Review process is not a blocker unless a concrete security, API contract,
document, or product defect is found.

Do not create a separate library, Git submodule, or extracted package now. Keep
the product as a single repository and one deployable control plane until there
is a second product, independent release cadence, or security provenance trigger.

## Approval Gates

| Gate | Owner | Evidence type | Runtime endpoint |
| --- | --- | --- | --- |
| Proposal packet ready | Deal owner | repository_and_runtime_artifact | `/api/v1/commercial_proposal_packets/latest` |
| Procurement path ready | Procurement owner | repository_and_runtime_artifact | `/api/v1/commercial_procurement_readiness/latest` |
| Contract and legal packet ready | Legal owner | repository_and_runtime_artifact | `/api/v1/commercial_contract_readiness/latest` |
| Financial value case ready | Economic buyer | repository_and_runtime_artifact | `/api/v1/commercial_value_readiness/latest` |
| Security acceptance ready | Security owner | repository_and_runtime_artifact | `/api/v1/commercial_security_attestations/latest` |
| Implementation readiness ready | Implementation owner | repository_and_runtime_artifact | `/api/v1/commercial_onboarding_readiness/latest` |
| Close readiness ready | Deal owner | repository_and_runtime_artifact | `/api/v1/commercial_close_readiness/latest` |
| Approval runtime packet ready | Stakeholder reviewer | repository_and_runtime_artifact | `/api/v1/commercial_purchase_approval_packets/latest` |
| Buyer signature authority | Buyer sponsor and legal owner | proposed_until_buyer_specific | buyer legal authority |
| Buyer budget and PO authority | Finance and procurement owner | proposed_until_buyer_specific | buyer finance authority |

## Runtime Shape

`TaskOrchestrator.commercial_purchase_approval_packet_report()` returns:

- `purchase_approval_status`: `commercial_purchase_approval_ready`,
  `commercial_purchase_approval_ready_with_warnings`, or
  `commercial_purchase_approval_blocked`.
- `measurement_status`: `local_commercial_purchase_approval_packet`.
- `approval_narrative`: title, promise, and buyer approval audience.
- `approval_summary`: ready, warning, blocked, endpoint, review-process, and
  Code Connect counts.
- `approval_gates`: buyer-side approval gates with evidence type, runtime
  endpoints, approval question, and next action.
- `required_runtime_endpoints`: runtime surfaces that back the approval packet.
- `related_runtime_reports`: proposal, close, procurement, contract, value,
  security, onboarding, operations, and analytics status.
- `library_split_decision`: the Ponytail packaging decision.

The endpoint reuses `/api/v1/commercial_proposal_packets/latest`,
`/api/v1/commercial_close_readiness/latest`,
`/api/v1/commercial_procurement_readiness/latest`,
`/api/v1/commercial_contract_readiness/latest`,
`/api/v1/commercial_value_readiness/latest`,
`/api/v1/commercial_security_attestations/latest`,
`/api/v1/commercial_onboarding_readiness/latest`,
`/api/v1/commercial_operations_readiness/latest`, `/api/v1/analytics_snapshots/latest`,
and `/admin/state`. Buyer signature authority, budget approval, purchase order,
finance authority, and go-live authorization remain warnings until supplied by
the buyer.

## Purchase Approval Status Rules

Ready: `commercial_purchase_approval_ready` means all approval gates are ready
and no buyer signature, budget, PO, or go-live inputs remain open.

Warning: `commercial_purchase_approval_ready_with_warnings` means repo-local
purchase approval evidence is ready while buyer signature authority, budget,
PO, or go-live authorization remain explicit warnings.

Blocked: `commercial_purchase_approval_blocked` means security failure, API
contract regression, document mismatch, runtime defect, missing local approval
evidence, or Code Connect usage blocks purchase approval.

## Plugin Responsibilities

- Product Design owns the buyer approval gate order and approval questions.
- Figma owns the editable stakeholder flow. Artifact:
  `KRW 2B Commercial Purchase Approval Packet`.
- Superpowers owns the implementation plan and verification loop.
- Ponytail keeps the approval packet repo-local and prevents premature library,
  submodule, or package extraction.
- Data Analytics owns the metric truthfulness model and the split between
  measured local evidence, proposed production metrics, and proposed
  buyer-specific metrics.

