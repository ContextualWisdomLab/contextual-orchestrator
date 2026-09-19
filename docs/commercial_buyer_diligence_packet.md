# Commercial Buyer Diligence Packet

This packet defines what a buyer can review for a KRW 2,000,000,000 buyer review
of Contextual Orchestrator. It is a due-diligence evidence map, not a valuation
guarantee, purchase commitment, revenue claim, or production compliance
certificate.

Figma Code Connect is not used.

Review process is not a blocker. Review delay, queued model review, or
automation review delay is only a process state. A blocker must be a concrete
security failure, API or document contract mismatch, or reproducible product
defect.

Do not create a separate library, Git submodule, or extracted package now. The
commercial value is the unified API plus admin evidence control plane, and a
split would add release, provenance, and procurement overhead before there is a
second consumer or independent release requirement.

## Evidence Types

| Evidence type | Meaning | Buyer interpretation |
|---|---|---|
| `measured_local` | Evidence is produced by the local runtime, tests, or current PR checks. | Ready for repo-level diligence, not a production SLO claim. |
| `repository_artifact` | Evidence is documented in committed source, docs, tests, or security metadata. | Ready when the artifact is present and linked to a product surface. |
| `figma_artifact` | Evidence exists in editable Figma, FigJam, or Figma Slides outputs. | Ready when recorded in `docs/figma_artifacts.md` and not generated through Code Connect. |
| `proposed_until_production` | Metric or control needs production telemetry, deployment history, or support operation records. | Warning until deployed and measured with production data. |
| `proposed_until_buyer_specific` | Evidence depends on a named buyer, contract model, legal questionnaire, or ROI case. | Warning until buyer-specific diligence starts. |

## Buyer Evidence Inventory

| Buyer question | Evidence path | Evidence type | Status interpretation |
|---|---|---|---|
| Can the system replace a direct model call with minimal integration work? | `/v1/chat/completions`, `tests/test_api_contract.py`, `docs/rest_api_design.md` | `repository_artifact` | Ready when API contract tests pass. |
| Can operators see the control plane state? | `/admin`, `/admin/state`, `docs/screen_design.md` | `repository_artifact` | Ready when admin state surfaces agent pools, policy, traces, access reports, replay, analytics, and readiness. |
| Can a buyer inspect sales readiness? | `/api/v1/sales_readiness/latest`, `tests/test_sales_readiness.py`, `docs/commercial_readiness.md` | `measured_local` | Ready for local diligence; production claims remain out of scope. |
| Can a buyer inspect KRW 2B commercial readiness? | `/api/v1/commercial_readiness/latest`, `tests/test_commercial_readiness.py`, `docs/commercial_completion_scorecard.md` | `measured_local` | Ready when failures are absent or remediation is explicit. |
| Are measured values separated from proposed KPIs? | `/api/v1/analytics_snapshots/latest`, `docs/analytics_spec.md` | `measured_local` | Ready when measured local values and proposed production metrics are not mixed. |
| Are security controls visible? | `SECURITY.md`, `tests/test_security_hardening.py`, GitHub CodeQL, Dependency review, Python supply chain, Trivy | `measured_local` | Ready when local tests and required security checks pass. |
| Can compliance inspect data exposure? | workflow trace records, access reports, `docs/product_planning.md` | `repository_artifact` | Ready when access lists are visible per workflow step. |
| Can evaluators replay or verify orchestration quality? | evaluation replay surface, verifier outcome records, `docs/screen_design.md` | `repository_artifact` | Ready for repo diligence; production replay volume remains proposed until deployed. |
| Can stakeholders review the product visually? | `docs/figma_artifacts.md`, Figma design file, FigJam board, Figma Slides deck | `figma_artifact` | Ready when editable artifacts are recorded and Code Connect remains unused. |
| Is the implementation plan auditable? | `docs/superpowers/plans/2026-07-02-commercial-plugin-readiness.md`, `docs/superpowers/plans/2026-07-02-commercial-buyer-diligence-packet.md` | `repository_artifact` | Ready when verification commands are listed and run. |
| Is package extraction justified now? | `docs/library_research.md`, `docs/commercial_plugin_operating_model.md` | `repository_artifact` | Ready because current decision keeps one repo and names extraction triggers. |
| Is buyer-specific ROI proven? | buyer ROI model, procurement questionnaire, contract-specific support plan | `proposed_until_buyer_specific` | Warning until a named buyer supplies diligence inputs. |
| Are production SLOs and support operations proven? | deployment telemetry, incident drills, support on-call records, uptime/SLO history | `proposed_until_production` | Warning until production operations exist and are measured. |

## Plugin Use In This Packet

| Plugin | Use | Packet output |
|---|---|---|
| Product Design | Converts buyer, operator, compliance, and procurement questions into reviewable evidence paths. | Buyer evidence inventory and status interpretation. |
| Figma | Adds an editable FigJam diagram named `KRW 2B Buyer Deal Room Evidence Matrix`. | Visual map from buyer questions to evidence types and blocker rules. |
| Superpowers | Keeps the work in a dated plan with explicit commands and acceptance criteria. | `docs/superpowers/plans/2026-07-02-commercial-buyer-diligence-packet.md`. |
| Ponytail | Rejects premature library, submodule, and extra dashboard work. | One repo, one product, one diligence packet. |
| Data Analytics | Labels measured local evidence separately from production and buyer-specific proposals. | Evidence type taxonomy and inventory labels. |

## Blocker Policy

Ready:

- local tests pass;
- required security and contract checks pass;
- buyer evidence paths are documented;
- Figma and FigJam artifacts are editable and recorded;
- measured local evidence is not presented as production telemetry.

Warning:

- production SLO, support, adoption, retention, and incident evidence is not yet
  measured;
- ROI evidence depends on a named buyer;
- model-review automation remains queued without a concrete defect.

Blocked:

- security test or security workflow failure;
- API contract regression;
- document contract mismatch;
- reproducible product defect;
- Figma Code Connect usage.
