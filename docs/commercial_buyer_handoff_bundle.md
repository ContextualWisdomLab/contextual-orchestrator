# Commercial Buyer Handoff Bundle

This bundle is the buyer-facing handoff surface for a KRW 2,000,000,000
commercial review of Contextual Orchestrator. It packages runtime reports,
repository documents, Figma artifacts, verification commands, and explicit
follow-up caveats into one API response and one review checklist.

Runtime endpoint: `/api/v1/buyer_handoff_bundles/latest`.

The target is buyer due-diligence readiness. It is not a valuation guarantee,
purchase commitment, revenue claim, or production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Review delay, queued model review, or
automation review delay is only a process state. A blocker must be a concrete
security failure, API or document contract mismatch, or reproducible product
defect.

Do not create a separate library, Git submodule, or extracted package now. The
handoff bundle reviews the unified product: one compatible API plus one admin
evidence control plane.

## Handoff Contents

| Bundle item | Reviewer | Source path or endpoint | Evidence type | Completion state |
|---|---|---|---|---|
| Runtime reports | Deal owner | `/api/v1/sales_readiness/latest`, `/api/v1/commercial_readiness/latest`, `/api/v1/buyer_evidence_manifests/latest`, `/api/v1/analytics_snapshots/latest` | `measured_local` | Ready when the buyer manifest has no blocked items. |
| Repository packet | Procurement reviewer | `README.md`, `docs/commercial_buyer_diligence_packet.md`, `docs/commercial_buyer_acceptance_runbook.md`, `docs/commercial_buyer_evidence_manifest.md`, `docs/commercial_buyer_handoff_bundle.md` | `repository_artifact` | Ready when buyer-facing packet documents are present. |
| Figma stakeholder artifacts | Stakeholder reviewer | `docs/figma_artifacts.md`, Figma design file, FigJam board, Figma Slides deck | `figma_artifact` | Ready when editable artifacts are recorded and Code Connect remains unused. |
| Verification commands | Technical reviewer | `tests/test_buyer_handoff_bundle.py`, `tests/test_buyer_evidence_manifest.py`, `tests/test_plugin_driven_artifacts.py`, `tests/test_api_contract.py`, `pytest -q` | `measured_local` | Ready when focused and full verification commands pass. |
| Packaging decision | Procurement and security reviewer | `docs/library_research.md`, `docs/commercial_plugin_operating_model.md` | `repository_artifact` | Ready because single repo and one deployable product remain the current decision. |
| Production handoff readiness | Customer operations reviewer | production SLO, incident drill, support rota, deployment history | `proposed_until_production` | Warning until a production deployment exists. |
| Buyer-specific commercial close | Economic buyer and legal reviewer | ROI model, legal questionnaire, data-processing terms, support plan | `proposed_until_buyer_specific` | Warning until a named buyer supplies inputs. |

## Runtime Shape

`/api/v1/buyer_handoff_bundles/latest` returns:

- `bundle_status`: `buyer_handoff_ready`, `buyer_handoff_ready_with_warnings`,
  or `buyer_handoff_blocked`;
- `measurement_status`: `local_buyer_handoff_bundle`;
- `included_artifacts`: measured local, repository, and Figma evidence ready for
  buyer review;
- `follow_up_items`: production and buyer-specific gaps that are warnings, not
  measured claims;
- `acceptance_gates`: go, warning, and blocked rules;
- `related_runtime_reports`: status values from the buyer manifest, commercial
  readiness, sales readiness, and analytics reports;
- `library_split_decision`: current single-product packaging decision and the
  future triggers for extraction.

## Acceptance Rules

Ready:

- every included artifact is ready;
- focused tests and full verification pass;
- the Figma artifact record includes `KRW 2B Buyer Handoff Bundle Workflow`;
- `/api/v1/buyer_handoff_bundles/latest` returns
  `local_buyer_handoff_bundle`;
- production and buyer-specific evidence remains explicitly caveated.

Warning:

- production SLO, incident drill, deployment, support, adoption, retention, or
  production telemetry is not measured yet;
- named-buyer ROI, legal, procurement, or deployment evidence is absent;
- review automation or reviewer process is queued without a concrete defect.

Blocked:

- concrete security failure;
- API contract regression;
- document contract mismatch;
- reproducible product defect;
- missing buyer handoff evidence for runtime reports, repository packet, Figma
  artifacts, verification commands, or packaging decision;
- Figma Code Connect usage.

## Plugin Responsibilities

| Plugin | Responsibility | Handoff output |
|---|---|---|
| Product Design | Keep the buyer handoff flow tied to operator evidence surfaces and procurement reviewers. | Handoff content model and acceptance rules. |
| Figma | Visualize the handoff flow in the existing FigJam board. | `KRW 2B Buyer Handoff Bundle Workflow`. |
| Superpowers | Keep the implementation plan and verification commands reproducible. | `docs/superpowers/plans/2026-07-02-buyer-handoff-bundle.md`. |
| Ponytail | Avoid a premature package split, submodule, new dashboard, or new dependency. | Single repo, one deployable product. |
| Data Analytics | Preserve measured versus proposed evidence labels. | `measured_local`, `repository_artifact`, `figma_artifact`, `proposed_until_production`, and `proposed_until_buyer_specific`. |

## FigJam Artifact

`KRW 2B Buyer Handoff Bundle Workflow` maps measured runtime reports,
repository packet, Figma artifacts, verification commands, production follow-up,
buyer-specific follow-up, and concrete-defect handling into the handoff decision.
