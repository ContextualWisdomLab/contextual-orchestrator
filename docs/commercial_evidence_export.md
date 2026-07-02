# Commercial Evidence Export

This document defines the portable commercial evidence export for the KRW
2,000,000,000 buyer due-diligence standard.

Runtime endpoint: `/api/v1/commercial_evidence_exports/latest`.

The export packages the current saleability decision, runtime readiness
reports, repository documents, Figma stakeholder artifacts, verification
commands, review-process policy, and packaging decision into one
machine-readable buyer review index.

It is not a valuation guarantee, purchase commitment, revenue claim, or
production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Review delay, review bot delay, queued model
review, or a pending check without a concrete failure is process state, not a
commercial evidence export blocker.

Do not create a separate library, Git submodule, or extracted package now. The
export reviews one product: a compatible inference API plus an admin evidence
control plane.

## Export Inputs

| Input | Runtime source | Export use |
|---|---|---|
| Saleability decision | `/api/v1/saleability_decisions/latest` | Primary ready, warning, or blocked decision. |
| Buyer handoff bundle | `/api/v1/buyer_handoff_bundles/latest` | Packaged buyer handoff state. |
| Buyer evidence manifest | `/api/v1/buyer_evidence_manifests/latest` | Buyer evidence index by owner, source, evidence type, and completion state. |
| Commercial readiness | `/api/v1/commercial_readiness/latest` | KRW 2,000,000,000 due-diligence criteria. |
| Sales readiness | `/api/v1/sales_readiness/latest` | API, admin, trace, replay, security, analytics, locale, and provider evidence. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest` | Measured local KPI and guardrail source status. |

## Runtime Shape

`/api/v1/commercial_evidence_exports/latest` returns:

- `export_status`: `commercial_export_ready`,
  `commercial_export_ready_with_warnings`, or `commercial_export_blocked`;
- `measurement_status`: `local_commercial_evidence_export`;
- `export_summary`: section count, concrete blocker count, warning count, and
  review-process blocker flag;
- `export_sections`: saleability, runtime report, buyer packet document, Figma,
  verification, review-process, and packaging evidence sections;
- `required_external_evidence`: production and buyer-specific evidence that
  remains warning-only until a live environment or named buyer exists;
- `concrete_blockers`: blocked saleability artifacts;
- `review_process_policy`: explicit rule that reviewer delay is not a blocker;
- `library_split_decision`: current single-product packaging decision;
- `export_links`: durable Figma, FigJam, endpoint, and document references.

## Export Status Rules

Ready:

- no blocked export section;
- no concrete saleability blocker;
- no required external evidence remains;
- focused and full verification commands pass.

Ready with warnings:

- no concrete blocker exists;
- production SLO, incident drill, deployment history, support ownership, or
  telemetry still requires a live customer environment;
- buyer-specific ROI, legal, procurement, data-processing, or support evidence
  still requires a named buyer.

Blocked:

- concrete security failure;
- API contract regression;
- document contract mismatch;
- reproducible product defect;
- missing saleability, handoff, manifest, readiness, analytics, admin, Figma, or
  verification evidence;
- Figma Code Connect usage.

## Plugin Responsibilities

| Plugin | Responsibility | Export output |
|---|---|---|
| Product Design | Keep export status visible in the existing operator observability flow. | Admin readiness row and bilingual labels. |
| Figma | Visualize the export path in the existing FigJam board. | `KRW 2B Commercial Evidence Export`. |
| Superpowers | Preserve an implementation-ready plan and verification checklist. | `docs/superpowers/plans/2026-07-02-commercial-evidence-export.md`. |
| Ponytail | Avoid extra package, submodule, dashboard, or dependency. | Single repo, one deployable product. |
| Data Analytics | Separate measured local evidence from proposed production or buyer-specific evidence. | `local_commercial_evidence_export` and `required_external_evidence`. |

## FigJam Artifact

`KRW 2B Commercial Evidence Export` maps saleability, runtime reports,
repository packet, Figma artifacts, verification commands, review-process
non-blocker policy, packaging decision, warning-only external evidence, and
commercial export ready or blocked states.
