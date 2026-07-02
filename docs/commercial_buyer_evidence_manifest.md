# Commercial Buyer Evidence Manifest

This manifest is the single review index for a KRW 2,000,000,000 buyer diligence review of Contextual Orchestrator. It tells a buyer where each evidence item lives, what kind of evidence it is, who reviews it, and whether the item is ready, caveated, or blocking.

Runtime endpoint: `/api/v1/buyer_evidence_manifests/latest`.

Handoff endpoint: `/api/v1/buyer_handoff_bundles/latest`.

The target is buyer due-diligence readiness. It is not a valuation guarantee,
purchase commitment, revenue claim, or production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Review delay, queued model review, or
automation review delay is only a process state. A blocker must be a concrete
security failure, API or document contract mismatch, or reproducible product
defect.

Do not create a separate library, Git submodule, or extracted package now. The
manifest reviews the unified product: one compatible API plus one admin evidence
control plane.

## Evidence Type Legend

| Evidence type | Meaning | Completion use |
|---|---|---|
| `measured_local` | Produced by local runtime, tests, or current PR checks. | Counts as ready for repo-level buyer diligence. |
| `repository_artifact` | Present in committed docs, source, tests, or security metadata. | Counts as ready when linked to a product surface. |
| `figma_artifact` | Present in editable Figma, FigJam, or Figma Slides artifacts. | Counts as ready when recorded in `docs/figma_artifacts.md`. |
| `proposed_until_production` | Requires production telemetry, deployment history, SLOs, incident drills, or support operations. | Counts as warning, not blocker, until production exists. |
| `proposed_until_buyer_specific` | Requires a named buyer, procurement questionnaire, legal review, support plan, or ROI case. | Counts as warning until the buyer supplies inputs. |

## Manifest Inventory

| Evidence item | Reviewer | Source path or endpoint | Evidence type | Completion state |
|---|---|---|---|---|
| Product scope | Economic buyer | `README.md`, `docs/product_planning.md`, `docs/commercial_readiness.md` | `repository_artifact` | Ready when the product remains one enterprise orchestration control plane. |
| Compatible inference API | Platform reviewer | `/v1/chat/completions`, `docs/rest_api_design.md`, `tests/test_api_contract.py` | `repository_artifact` | Ready when API contract tests pass. |
| Admin evidence control plane | Platform operator | `/admin`, `/admin/state`, `docs/screen_design.md` | `repository_artifact` | Ready when operator state exposes agent pool, policy, workflow trace, access reports, replay, analytics, and readiness. |
| Sales readiness | Product owner | `/api/v1/sales_readiness/latest`, `tests/test_sales_readiness.py` | `measured_local` | Ready when remediation is explicit and local report is not presented as production certification. |
| Commercial readiness | Economic buyer | `/api/v1/commercial_readiness/latest`, `tests/test_commercial_readiness.py`, `docs/commercial_completion_scorecard.md` | `measured_local` | Ready when KRW 2,000,000,000 diligence criteria have no unexplained failures. |
| Analytics honesty | Analytics reviewer | `/api/v1/analytics_snapshots/latest`, `docs/analytics_spec.md` | `measured_local` | Ready when measured and proposed claims remain separated. |
| Access-list evidence | Security and compliance reviewer | `/api/v1/access_reports/{workflow_run_id}`, `docs/product_planning.md` | `repository_artifact` | Ready when workflow trace and access-list exposure are inspectable. |
| Evaluation replay evidence | Quality reviewer | `/api/v1/evaluation_runs`, `docs/screen_design.md` | `repository_artifact` | Ready for repo diligence; production replay volume is caveated until deployed. |
| Security posture | Security reviewer | `SECURITY.md`, `tests/test_security_hardening.py`, CodeQL, Dependency review, Python supply chain, Trivy | `measured_local` | Ready when required security checks pass. Block on concrete security failure. |
| Visual stakeholder evidence | Stakeholder reviewer | `docs/figma_artifacts.md`, Figma design file, FigJam board, Figma Slides deck | `figma_artifact` | Ready when editable artifacts are recorded and Code Connect remains unused. |
| Buyer diligence packet | Procurement reviewer | `docs/commercial_buyer_diligence_packet.md` | `repository_artifact` | Ready when buyer questions map to evidence paths and caveats. |
| Buyer acceptance runbook | Procurement reviewer | `docs/commercial_buyer_acceptance_runbook.md` | `repository_artifact` | Ready when go, warning, and no-go rules are explicit. |
| Packaging decision | Procurement and security reviewer | `docs/library_research.md`, `docs/commercial_plugin_operating_model.md` | `repository_artifact` | Ready because single repo and one deployable product remain the current decision. |
| Buyer handoff bundle | Deal owner | `/api/v1/buyer_handoff_bundles/latest`, `docs/commercial_buyer_handoff_bundle.md` | `measured_local` | Ready when runtime reports, repository packet, Figma artifacts, verification commands, packaging decision, and follow-ups are packaged for buyer review. |
| Production SLO and support proof | Customer operations reviewer | production telemetry, incident drill records, support ownership | `proposed_until_production` | Warning until a production deployment exists. |
| Buyer-specific ROI and legal proof | Economic buyer and procurement | ROI model, legal questionnaire, data-processing terms, support plan | `proposed_until_buyer_specific` | Warning until a named buyer supplies inputs. |

## Completion Rules

Ready:

- every `repository_artifact`, `figma_artifact`, and `measured_local` item has a
  named source path or endpoint;
- local verification passes;
- required security checks pass or are still running without a concrete failure;
- `docs/figma_artifacts.md` records `KRW 2B Buyer Evidence Manifest Workflow`;
- `/api/v1/buyer_evidence_manifests/latest` returns
  `local_buyer_evidence_manifest`;
- `/api/v1/buyer_handoff_bundles/latest` returns
  `local_buyer_handoff_bundle`;
- production and buyer-specific gaps are labeled as warnings, not measured
  evidence.

Warning:

- production telemetry, SLO, support, adoption, retention, or incident evidence
  is not measured yet;
- named-buyer ROI, legal, procurement, or deployment evidence is absent;
- `opencode-review`, model review, or reviewer automation is still queued
  without a concrete defect.

Blocked:

- security test or security workflow failure;
- API contract regression;
- document contract mismatch;
- reproducible product defect;
- missing manifest evidence for the compatibility API, admin control plane,
  access-list evidence, readiness endpoints, Figma artifacts, or caveat model;
- Figma Code Connect usage.

## Plugin Responsibilities

| Plugin | Responsibility | Manifest output |
|---|---|---|
| Product Design | Convert buyer review questions into owners, evidence paths, and completion states. | Manifest inventory table. |
| Figma | Visualize the manifest flow in the existing FigJam board. | `KRW 2B Buyer Evidence Manifest Workflow`. |
| Superpowers | Keep execution steps and verification commands reproducible. | `docs/superpowers/plans/2026-07-02-commercial-buyer-evidence-manifest.md`. |
| Ponytail | Prevent unnecessary product split, dashboard expansion, or dependency addition. | Single repo, one product, no new framework. |
| Data Analytics | Preserve evidence type labels and keep proposed metrics separate from measured values. | Evidence type legend and analytics honesty row. |
