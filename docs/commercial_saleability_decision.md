# Commercial Saleability Decision

This document defines the final KRW 2,000,000,000 saleability decision gate for
Contextual Orchestrator. It answers whether the product is ready for buyer
diligence, ready with explicit warnings, or blocked by a concrete defect.

Runtime endpoint: `/api/v1/saleability_decisions/latest`.

The target is buyer due-diligence readiness. It is not a valuation guarantee,
purchase commitment, revenue claim, or production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Review delay, queued model review, pending
automation review, or a pending check with no concrete failure is a process
state, not a saleability blocker.

Do not create a separate library, Git submodule, or extracted package now. The
decision gate reviews one product: a compatible inference API plus an admin
evidence control plane.

## Decision Inputs

| Input | Runtime source | Decision use |
|---|---|---|
| Buyer handoff bundle | `/api/v1/buyer_handoff_bundles/latest` | Primary saleability input. |
| Buyer evidence manifest | `/api/v1/buyer_evidence_manifests/latest` | Confirms buyer evidence has named sources and caveats. |
| Commercial readiness | `/api/v1/commercial_readiness/latest` | Confirms KRW 2,000,000,000 diligence criteria. |
| Sales readiness | `/api/v1/sales_readiness/latest` | Confirms API, admin, trace, replay, security, analytics, locale, and provider evidence. |

## Runtime Shape

`/api/v1/saleability_decisions/latest` returns:

- `saleability_status`: `saleability_ready`,
  `saleability_ready_with_warnings`, or `saleability_blocked`;
- `measurement_status`: `local_saleability_decision`;
- `decision_summary`: included artifact count, concrete blocker count, warning
  count, and review-process blocker flag;
- `decision_basis`: the readiness and handoff reports used for the decision;
- `concrete_blockers`: blocked included artifacts from the buyer handoff bundle;
- `warning_conditions`: production and buyer-specific follow-up items;
- `review_process_policy`: explicit rule that review process delay is not a
  blocker;
- `library_split_decision`: current single-product packaging decision.

## Decision Rules

Ready:

- no blocked included artifacts;
- no warning follow-up items;
- focused and full verification commands pass;
- `/api/v1/saleability_decisions/latest` returns
  `local_saleability_decision`.

Ready with warnings:

- no blocked included artifacts;
- production SLO, incident drill, deployment, support, adoption, retention, or
  production telemetry remains unmeasured;
- buyer-specific ROI, legal, procurement, or deployment evidence remains
  uncollected;
- review process is pending without a concrete failure.

Blocked:

- concrete security failure;
- API contract regression;
- document contract mismatch;
- reproducible product defect;
- missing runtime evidence for saleability, buyer handoff, buyer manifest,
  commercial readiness, sales readiness, or analytics;
- Figma Code Connect usage.

## Plugin Responsibilities

| Plugin | Responsibility | Decision output |
|---|---|---|
| Product Design | Keep the decision visible in the existing operator observability flow. | Admin readiness status and decision labels. |
| Figma | Visualize the final gate in the existing FigJam board. | `KRW 2B Saleability Decision Gate`. |
| Superpowers | Preserve an implementation-ready plan and verification checklist. | `docs/superpowers/plans/2026-07-02-saleability-decision-gate.md`. |
| Ponytail | Prevent a premature library split, submodule, dashboard, or dependency. | Single repo, one deployable product. |
| Data Analytics | Keep local measured evidence separate from warning follow-ups. | `local_saleability_decision`, concrete blockers, and warning conditions. |

## FigJam Artifact

`KRW 2B Saleability Decision Gate` maps the buyer handoff bundle, concrete
blocker detection, review-process non-blocker policy, warning follow-ups, and
ready or blocked saleability states.
