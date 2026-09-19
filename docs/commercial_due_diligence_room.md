# Commercial Due Diligence Room

Runtime endpoint: `/api/v1/commercial_due_diligence_rooms/latest`.

This document defines the KRW 2,000,000,000 buyer due diligence room for
Contextual Orchestrator as one enterprise orchestration control plane. The room
packages purchase approval, runtime API evidence, admin trace/access evidence,
security, commercial terms, value analytics, implementation readiness, Figma,
review-policy, and packaging evidence into one buyer diligence artifact for
finance, procurement, legal, security, platform, product, and implementation
reviewers.

It is not a valuation guarantee, purchase commitment, signed order, legal
opinion, production compliance certificate, third-party attestation, or revenue
proof. Figma Code Connect is not used. Review process is not a blocker unless a
concrete security, API contract, document, or product defect is found.

Do not create a separate library, Git submodule, or extracted package now. Keep
the product as a single repository and one deployable control plane until there
is a second product, independent release cadence, or security provenance trigger.

## Diligence Sections

| Section | Reviewer | Evidence type | Runtime endpoint |
| --- | --- | --- | --- |
| Purchase approval packet | Purchase committee | repository_and_runtime_artifact | `/api/v1/commercial_purchase_approval_packets/latest` |
| Runtime API evidence | Platform reviewer | repository_and_runtime_artifact | `/v1/chat/completions` |
| Admin trace evidence | Operator reviewer | repository_and_runtime_artifact | `/admin` |
| Security and compliance | Security reviewer | repository_and_runtime_artifact | `/api/v1/commercial_security_attestations/latest` |
| Commercial terms | Legal and procurement reviewers | repository_and_runtime_artifact | `/api/v1/commercial_contract_readiness/latest` |
| Value and analytics | Economic reviewer | repository_and_runtime_artifact | `/api/v1/analytics_snapshots/latest` |
| Implementation readiness | Implementation and operations reviewers | repository_and_runtime_artifact | `/api/v1/commercial_operations_readiness/latest` |
| Figma and design review | Product design reviewer | repository_and_runtime_artifact | `/api/v1/commercial_due_diligence_rooms/latest` |
| Buyer authority documents | Buyer sponsor | proposed_until_buyer_specific | buyer authority |
| Production and external attestations | Production and security owners | proposed_until_buyer_specific | hosted production evidence |

## Runtime Shape

`TaskOrchestrator.commercial_due_diligence_room_report()` returns:

- `due_diligence_status`: `commercial_due_diligence_ready`,
  `commercial_due_diligence_ready_with_warnings`, or
  `commercial_due_diligence_blocked`.
- `measurement_status`: `local_commercial_due_diligence_room`.
- `diligence_narrative`: title, promise, and buyer diligence audience.
- `diligence_summary`: ready, warning, blocked, endpoint, review-process, and
  Code Connect counts.
- `diligence_sections`: buyer diligence room sections with evidence type,
  runtime endpoints, diligence question, and next action.
- `required_runtime_endpoints`: runtime surfaces that back the diligence room.
- `buyer_missing_artifacts`: buyer authority, production telemetry, and
  third-party attestation artifacts that are not measured local evidence.
- `related_runtime_reports`: purchase approval, proposal, completion, demo,
  close, procurement, contract, value, security, onboarding, operations, and
  analytics status.
- `library_split_decision`: the Ponytail packaging decision.

The endpoint reuses `/api/v1/commercial_purchase_approval_packets/latest`,
`/api/v1/commercial_proposal_packets/latest`,
`/api/v1/commercial_completion_scorecards/latest`,
`/api/v1/commercial_demo_scenarios/latest`,
`/api/v1/commercial_buyer_acceptance_workflows/latest`,
`/api/v1/commercial_close_readiness/latest`,
`/api/v1/commercial_procurement_readiness/latest`,
`/api/v1/commercial_contract_readiness/latest`,
`/api/v1/commercial_value_readiness/latest`,
`/api/v1/commercial_security_attestations/latest`,
`/api/v1/commercial_onboarding_readiness/latest`,
`/api/v1/commercial_operations_readiness/latest`, `/api/v1/analytics_snapshots/latest`,
and `/admin/state`.

## Due Diligence Status Rules

Ready: `commercial_due_diligence_ready` means all diligence sections are ready
and no buyer authority, production, or third-party evidence remains open.

Warning: `commercial_due_diligence_ready_with_warnings` means repo-local
diligence room evidence is ready while buyer authority, production telemetry, or
external attestations remain explicit warnings.

Blocked: `commercial_due_diligence_blocked` means security failure, API contract
regression, document mismatch, runtime defect, missing local diligence evidence,
or Code Connect usage blocks buyer diligence.

## Plugin Responsibilities

- Product Design owns the diligence section order and reviewer questions.
- Figma owns the editable stakeholder flow. Artifact:
  `KRW 2B Commercial Due Diligence Room`.
- Superpowers owns the implementation plan and verification loop.
- Ponytail keeps the due diligence room repo-local and prevents premature
  library, submodule, or package extraction.
- Data Analytics owns the metric truthfulness model and the split between
  measured local evidence, proposed production metrics, and proposed
  buyer-specific metrics.
