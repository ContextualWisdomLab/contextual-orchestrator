# Commercial Investment Committee Memo

Runtime endpoint: `/api/v1/commercial_investment_committee_memos/latest`.

This document defines the KRW 2,000,000,000 investment committee memo for
Contextual Orchestrator as one enterprise orchestration control plane. The memo
packages due diligence, purchase approval, financial case, risk/security,
commercial terms, implementation readiness, Figma, review-policy, and packaging
evidence into one executive recommendation artifact for investment committee,
finance, procurement, legal, security, and implementation reviewers.

It is not a valuation guarantee, purchase commitment, signed order, legal
opinion, production compliance certificate, third-party attestation, or revenue
proof. Figma Code Connect is not used. Review process is not a blocker unless a
concrete security, API contract, document, or product defect is found.

Do not create a separate library, Git submodule, or extracted package now. Keep
the product as a single repository and one deployable control plane until there
is a second product, independent release cadence, or security provenance trigger.

## Memo Sections

| Section | Reviewer | Evidence type | Runtime endpoint |
| --- | --- | --- | --- |
| Executive recommendation | Investment committee chair | repository_and_runtime_artifact | `/api/v1/commercial_investment_committee_memos/latest` |
| Due diligence room ready | Diligence owner | repository_and_runtime_artifact | `/api/v1/commercial_due_diligence_rooms/latest` |
| Purchase approval ready | Purchase sponsor | repository_and_runtime_artifact | `/api/v1/commercial_purchase_approval_packets/latest` |
| Financial case | Economic buyer | repository_and_runtime_artifact | `/api/v1/commercial_value_readiness/latest` |
| Risk and security summary | Security reviewer | repository_and_runtime_artifact | `/api/v1/commercial_security_attestations/latest` |
| Commercial terms summary | Legal and procurement reviewers | repository_and_runtime_artifact | `/api/v1/commercial_contract_readiness/latest` |
| Implementation readiness summary | Implementation owner | repository_and_runtime_artifact | `/api/v1/commercial_operations_readiness/latest` |
| Design and Figma review | Product design reviewer | repository_and_runtime_artifact | `/api/v1/commercial_investment_committee_memos/latest` |
| Buyer final authority | Buyer sponsor | proposed_until_buyer_specific | buyer executive authority |
| Production and external evidence | Production and security owners | proposed_until_buyer_specific | hosted production evidence |

## Runtime Shape

`TaskOrchestrator.commercial_investment_committee_memo_report()` returns:

- `investment_committee_status`: `commercial_investment_committee_ready`,
  `commercial_investment_committee_ready_with_warnings`, or
  `commercial_investment_committee_blocked`.
- `measurement_status`: `local_commercial_investment_committee_memo`.
- `executive_recommendation`: title, recommendation status, recommendation
  text, and committee audience.
- `memo_summary`: ready, warning, blocked, endpoint, review-process, and Code
  Connect counts.
- `memo_sections`: committee memo sections with evidence type, runtime
  endpoints, committee question, and next action.
- `committee_decision_questions`: final executive questions that separate local
  product evidence from buyer and external conditions.
- `buyer_missing_artifacts`: buyer authority, production telemetry, and
  third-party attestation artifacts that are not measured local evidence.
- `related_runtime_reports`: due diligence, purchase approval, proposal,
  completion, demo, buyer acceptance, close, procurement, contract, value,
  security, onboarding, operations, analytics, and admin status.
- `library_split_decision`: the Ponytail packaging decision.

The endpoint reuses `/api/v1/commercial_due_diligence_rooms/latest`,
`/api/v1/commercial_purchase_approval_packets/latest`,
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

## Investment Committee Status Rules

Ready: `commercial_investment_committee_ready` means all memo sections are ready
and no buyer authority, production, or third-party evidence remains open.

Warning: `commercial_investment_committee_ready_with_warnings` means repo-local
committee memo evidence is ready while buyer authority, production telemetry, or
external attestations remain explicit warnings.

Blocked: `commercial_investment_committee_blocked` means security failure, API
contract regression, document mismatch, runtime defect, missing local memo
evidence, or Code Connect usage blocks committee recommendation.

## Plugin Responsibilities

- Product Design owns the memo section order and committee questions.
- Figma owns the editable stakeholder flow. Artifact:
  `KRW 2B Commercial Investment Committee Memo`.
- Superpowers owns the implementation plan and verification loop.
- Ponytail keeps the memo repo-local and prevents premature library, submodule,
  or package extraction.
- Data Analytics owns the metric truthfulness model and the split between
  measured local evidence, proposed production metrics, and proposed
  buyer-specific metrics.
