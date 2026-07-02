# Commercial Saleability Gate

This document defines the final KRW 2,000,000,000 commercial saleability gate
for Contextual Orchestrator.

Runtime endpoint: `/api/v1/commercial_saleability_gates/latest`.

The gate is a buyer close review packet. It wraps the existing saleability
decision and commercial investment committee memo instead of creating another
product, package, library, or submodule.

Figma Code Connect is not used.

Review process is not a blocker. Review bot delay, reviewer delay, queued
model review, or pending review process without a concrete failure is tracked
as process latency, not product incompleteness.

Do not create a separate library, Git submodule, or extracted package now. Keep
one enterprise orchestration control plane until there is repo-local evidence
for a second product, independent release cadence, or buyer security provenance
requirement.

## Gate Inputs

| Input | Runtime or document | Purpose |
|---|---|---|
| Saleability decision | `/api/v1/saleability_decisions/latest` | Primary local buyer diligence status. |
| Investment committee memo | `/api/v1/commercial_investment_committee_memos/latest` | Executive recommendation and committee conditions. |
| Due diligence room | `/api/v1/commercial_due_diligence_rooms/latest` | Buyer evidence room and missing artifact policy. |
| Purchase approval packet | `/api/v1/commercial_purchase_approval_packets/latest` | Finance, procurement, legal, security, and implementation gates. |
| Close and terms readiness | `/api/v1/commercial_close_readiness/latest`, `/api/v1/commercial_contract_readiness/latest`, `/api/v1/commercial_procurement_readiness/latest` | Signature, contract, and procurement conditions. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest` | Local measured metric provenance. |
| Figma artifacts | `docs/figma_artifacts.md` | Editable stakeholder flow record without Code Connect. |

## Runtime Shape

`/api/v1/commercial_saleability_gates/latest` returns:

- `saleability_gate_status`: `commercial_saleability_gate_ready`,
  `commercial_saleability_gate_ready_with_warnings`, or
  `commercial_saleability_gate_blocked`;
- `target_contract_value_krw` and `target_contract_value_display`;
- `measurement_status`: `local_commercial_saleability_gate`;
- `source_note`: local evidence caveat and non-guarantee statement;
- `go_no_go_recommendation`: final go, go-with-conditions, or no-go status;
- `gate_summary`: check count, ready count, warning count, blocker count,
  endpoint count, review-process policy, and Code Connect exclusion;
- `gate_checks`: owner-scoped ready, warning, or blocked checks;
- `required_runtime_endpoints`: endpoint chain needed for buyer close review;
- `buyer_close_packet`: document, endpoint, and external-condition index;
- `metric_provenance`: measured local sources separated from proposed buyer or
  production inputs;
- `operator_next_actions`: next concrete operator steps;
- `final_buyer_authority_gaps`: buyer authority artifacts still required;
- `concrete_blockers`: concrete defects that block buyer close review;
- `review_process_policy`: review-process non-blocker definition;
- `library_split_decision`: single-product packaging decision;
- `plugin_traceability`: Product Design, Figma, Superpowers, Ponytail, and Data
  Analytics traceability;
- `gate_links`: Figma, FigJam, runtime endpoint, and documentation links.

## Gate Status Rules

| Status | Rule |
|---|---|
| `commercial_saleability_gate_ready` | All local gate checks are ready and no buyer authority, production, or third-party evidence remains open. |
| `commercial_saleability_gate_ready_with_warnings` | Local saleability and committee evidence are ready while buyer authority, production telemetry, or external attestations remain explicit warnings. |
| `commercial_saleability_gate_blocked` | Security failure, API contract regression, document mismatch, runtime defect, missing local gate evidence, or Code Connect usage blocks buyer close review. |

## Metric Provenance

Measured local sources:

- `/api/v1/saleability_decisions/latest`
- `/api/v1/commercial_investment_committee_memos/latest`
- `/api/v1/analytics_snapshots/latest`

Proposed or buyer-specific sources:

- buyer final authority;
- production telemetry;
- third-party security attestation.

## KRW 2B Commercial Saleability Gate

The KRW 2B Commercial Saleability Gate is complete when:

- `/api/v1/commercial_saleability_gates/latest` returns
  `local_commercial_saleability_gate`;
- no concrete security, API contract, runtime, document, or product blocker is
  present;
- buyer final authority and production or external proof gaps are explicit
  warnings, not hidden blockers;
- admin readiness, OpenAPI, README, REST API docs, analytics spec, Figma artifact
  record, Superpowers plan, and tests all reference the same endpoint;
- Figma Code Connect remains unused.
