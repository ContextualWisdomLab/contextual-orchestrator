# Commercial Proposal Packet

Runtime endpoint: `/api/v1/commercial_proposal_packets/latest`.

This document defines the KRW 2,000,000,000 buyer proposal packet for
Contextual Orchestrator as one enterprise orchestration control plane. The
proposal packages completion, demo, buyer acceptance, value, security,
contract, onboarding, operations, analytics, Figma, review-policy, and packaging
evidence into sections a buyer can review before a commercial negotiation.

It is not a valuation guarantee, purchase commitment, signed order, legal
opinion, production compliance certificate, or revenue proof. Figma Code Connect is not used.
Review process is not a blocker unless a concrete security, API contract,
document, or product defect is found.

Do not create a separate library, Git submodule, or extracted package now. Keep
the product as a single repository and one deployable control plane until there
is a second product, independent release cadence, or security provenance trigger.

## Proposal Sections

| Section | Owner | Evidence type | Runtime endpoint |
| --- | --- | --- | --- |
| Executive summary | Deal owner | repository_and_runtime_artifact | `/api/v1/commercial_completion_scorecards/latest` |
| Product scope | Product owner | repository_artifact | repository docs |
| Buyer value case | Economic buyer | repository_and_runtime_artifact | `/api/v1/commercial_value_readiness/latest` |
| Demo and acceptance path | Product design owner | repository_and_runtime_artifact | `/api/v1/commercial_demo_scenarios/latest` |
| Technical evidence | Platform reviewer | repository_and_runtime_artifact | `/v1/chat/completions` |
| Security and compliance | Security reviewer | repository_and_runtime_artifact | `/api/v1/commercial_security_attestations/latest` |
| Implementation and operations | Operations owner | repository_and_runtime_artifact | `/api/v1/commercial_operations_readiness/latest` |
| Proposal review packet | Stakeholder reviewer | repository_and_runtime_artifact | `/api/v1/commercial_proposal_packets/latest` |
| Commercial terms follow-ups | Deal owner | proposed_until_buyer_specific | `/api/v1/commercial_contract_readiness/latest` |
| Production and buyer inputs | Buyer sponsor | proposed_until_buyer_specific | buyer environment |

## Runtime Shape

`TaskOrchestrator.commercial_proposal_packet_report()` returns:

- `proposal_status`: `commercial_proposal_ready`,
  `commercial_proposal_ready_with_warnings`, or `commercial_proposal_blocked`.
- `measurement_status`: `local_commercial_proposal_packet`.
- `proposal_narrative`: title, promise, and target audience.
- `proposal_summary`: ready, warning, blocked, endpoint, review-process, and
  Code Connect counts.
- `proposal_sections`: buyer-facing proposal sections with evidence type,
  runtime endpoints, buyer message, and next action.
- `required_runtime_endpoints`: runtime surfaces that back the proposal packet.
- `related_runtime_reports`: completion, demo, acceptance, value, security,
  contract, onboarding, operations, and analytics status.
- `library_split_decision`: the Ponytail packaging decision.

The endpoint reuses `/api/v1/commercial_completion_scorecards/latest`,
`/api/v1/commercial_demo_scenarios/latest`,
`/api/v1/commercial_buyer_acceptance_workflows/latest`,
`/api/v1/commercial_value_readiness/latest`,
`/api/v1/commercial_security_attestations/latest`,
`/api/v1/commercial_contract_readiness/latest`,
`/api/v1/commercial_onboarding_readiness/latest`,
`/api/v1/commercial_operations_readiness/latest`, `/api/v1/analytics_snapshots/latest`,
and `/admin/state`. Proposed production, legal, pricing, signature, or
buyer-specific inputs remain warnings until supplied by the buyer or deployment
environment.

## Proposal Status Rules

Ready: `commercial_proposal_ready` means all proposal sections are ready and no
buyer-specific commercial or production inputs remain open.

Warning: `commercial_proposal_ready_with_warnings` means repo-local proposal
evidence is ready while pricing, legal, ROI, production, support, or signature
inputs remain explicit warnings.

Blocked: `commercial_proposal_blocked` means security failure, API contract
regression, document mismatch, runtime defect, missing local proposal evidence,
or Code Connect usage blocks the proposal.

## Plugin Responsibilities

- Product Design owns the buyer-facing proposal section order and the demo to
  acceptance story.
- Figma owns the editable stakeholder flow. Artifact:
  `KRW 2B Commercial Proposal Packet`.
- Superpowers owns the implementation plan and verification loop.
- Ponytail keeps the proposal packet repo-local and prevents premature library,
  submodule, or package extraction.
- Data Analytics owns the metric truthfulness model and the split between
  measured local evidence, proposed production metrics, and proposed
  buyer-specific metrics.

