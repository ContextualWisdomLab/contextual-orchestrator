# Commercial Acceptance Check

This document defines the runtime buyer acceptance check for the KRW
2,000,000,000 commercial due-diligence standard.

Target contract value: KRW 2,000,000,000.

Runtime endpoint: `/api/v1/commercial_acceptance_checks/latest`.

The acceptance check evaluates the current commercial evidence export, runtime
endpoint chain, buyer packet documents, admin operator surface, verification
evidence, Figma stakeholder artifacts, review-process policy, packaging
decision, and production or buyer-specific evidence gaps.

It is not a valuation guarantee, purchase commitment, revenue claim, or
production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Review delay, review bot delay, queued model
review, or a pending check without a concrete failure is process state, not a
commercial acceptance blocker.

Do not create a separate library, Git submodule, or extracted package now. The
acceptance check reviews one product: a compatible inference API plus an admin
evidence control plane.

## Acceptance Inputs

| Input | Runtime or repository source | Acceptance use |
|---|---|---|
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Primary evidence export input. |
| Saleability decision | `/api/v1/saleability_decisions/latest` | Concrete blocker and warning source. |
| Buyer handoff bundle | `/api/v1/buyer_handoff_bundles/latest` | Handoff status and buyer package state. |
| Buyer evidence manifest | `/api/v1/buyer_evidence_manifests/latest` | Evidence item source, owner, and caveat model. |
| Readiness endpoints | `/api/v1/sales_readiness/latest`, `/api/v1/commercial_readiness/latest` | Local readiness gate source. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest` | Measured local KPI and guardrail source. |
| Admin console | `/admin` | Operator-visible acceptance status. |

## Runtime Shape

`/api/v1/commercial_acceptance_checks/latest` returns:

- `acceptance_status`: `commercial_acceptance_ready`,
  `commercial_acceptance_ready_with_warnings`, or
  `commercial_acceptance_blocked`;
- `measurement_status`: `local_commercial_acceptance_check`;
- `acceptance_summary`: item count, blocker count, warning count, and
  review-process blocker flag;
- `acceptance_items`: runtime endpoint chain, buyer packet document, admin,
  verification, Figma, review-process, and packaging checks;
- `follow_up_items`: production and buyer-specific evidence gaps;
- `concrete_blockers`: blocked commercial evidence export items;
- `acceptance_gates`: go, warning, and blocked rules;
- `review_process_policy`: explicit rule that review delay is not a blocker;
- `library_split_decision`: current single-product packaging decision.

## Acceptance Status Rules

Ready:

- all acceptance items are ready;
- no concrete blocker exists;
- no production or buyer-specific evidence gap remains.

Ready with warnings:

- all local acceptance items are ready;
- production SLO, incident drill, deployment history, support ownership, or
  telemetry still requires a live customer environment;
- buyer-specific ROI, legal, procurement, data-processing, or support evidence
  still requires a named buyer;
- review process is pending without a concrete failure.

Blocked:

- concrete security failure;
- API contract regression;
- document contract mismatch;
- reproducible product defect;
- missing admin, runtime, buyer packet, Figma, verification, export, or
  readiness evidence;
- Figma Code Connect usage.

## Plugin Responsibilities

| Plugin | Responsibility | Acceptance output |
|---|---|---|
| Product Design | Keep acceptance status visible in the existing operator observability flow. | Admin readiness row and bilingual labels. |
| Figma | Visualize the acceptance path in the existing FigJam board. | `KRW 2B Commercial Acceptance Check`. |
| Superpowers | Preserve an implementation-ready plan and verification checklist. | `docs/superpowers/plans/2026-07-02-commercial-acceptance-check.md`. |
| Ponytail | Avoid a new app surface, library split, submodule, or dependency. | Single repo, one deployable product. |
| Data Analytics | Separate measured local acceptance from proposed production or buyer-specific evidence. | `local_commercial_acceptance_check`, `acceptance_items`, and `follow_up_items`. |

## FigJam Artifact

`KRW 2B Commercial Acceptance Check` maps the commercial evidence export,
runtime endpoint chain, buyer packet documents, admin operator surface,
verification evidence, Figma artifacts, review-process non-blocker policy,
packaging decision, external evidence gaps, and final acceptance status.
