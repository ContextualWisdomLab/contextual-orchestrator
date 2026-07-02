# Commercial Buyer Acceptance Runbook

This runbook defines the buyer-facing go/no-go workflow for a KRW 2,000,000,000 commercial review of Contextual Orchestrator. It turns the existing readiness endpoints, documentation, Figma artifacts, and buyer diligence packet into an acceptance sequence.

The target is buyer due-diligence readiness. It is not a valuation guarantee,
purchase commitment, revenue claim, or production compliance certificate.

Figma Code Connect is not used.

Review process is not a blocker. Review delay, queued model review, or
automation review delay is only a process state. A blocker must be a concrete
security failure, API or document contract mismatch, or reproducible product
defect.

Do not create a separate library, Git submodule, or extracted package now. The
commercial acceptance workflow reviews the unified product: one compatible API
plus one admin evidence control plane.

## Acceptance Workflow

| Step | Owner | Evidence | Decision |
|---|---|---|---|
| 1. Confirm product scope | Product owner | `README.md`, `docs/product_planning.md`, `docs/commercial_readiness.md` | Proceed when the product is framed as one orchestration control plane, not separate Fugu, TRINITY, or Conductor products. |
| 2. Confirm integration surface | Platform reviewer | `/v1/chat/completions`, `docs/rest_api_design.md`, `tests/test_api_contract.py` | Proceed when API compatibility evidence is present and tests pass. |
| 3. Confirm operator evidence | Platform operator | `/admin`, `/admin/state`, `docs/screen_design.md` | Proceed when agent pool, policy, trace, access report, replay, analytics, and readiness surfaces are visible. |
| 4. Confirm readiness endpoints | Product owner | `/api/v1/sales_readiness/latest`, `/api/v1/commercial_readiness/latest`, `tests/test_sales_readiness.py`, `tests/test_commercial_readiness.py` | Proceed when local evidence is ready or remediation is explicit. |
| 5. Confirm security posture | Security reviewer | `SECURITY.md`, `tests/test_security_hardening.py`, CodeQL, Dependency review, Python supply chain, Trivy | Proceed when required checks pass. Block on concrete failure. |
| 6. Confirm metric honesty | Analytics reviewer | `/api/v1/analytics_snapshots/latest`, `docs/analytics_spec.md`, `docs/commercial_buyer_diligence_packet.md` | Proceed when `measured_local`, `repository_artifact`, `figma_artifact`, `proposed_until_production`, and `proposed_until_buyer_specific` claims are separated. |
| 7. Confirm visual review path | Stakeholder reviewer | `docs/figma_artifacts.md`, FigJam board, Figma design file, Figma Slides deck | Proceed when editable artifacts are recorded and Code Connect remains unused. |
| 8. Confirm packaging decision | Procurement reviewer | `docs/library_research.md`, `docs/commercial_plugin_operating_model.md` | Proceed when one repo and one deployable product remain the current packaging decision. |
| 9. Confirm buyer-specific inputs | Buyer and account team | ROI model, security questionnaire, support plan, deployment target | Mark as buyer-specific follow-up until supplied by a named buyer. |

## Go, Warning, No-Go Rules

Go:

- local verification passes;
- required security and contract checks pass;
- `/api/v1/commercial_readiness/latest` has no unexplained failures;
- FigJam contains `KRW 2B Buyer Acceptance Go No Go Workflow`;
- the buyer diligence packet links every major evidence path;
- production and buyer-specific gaps are labeled as caveats instead of measured
  claims.

Warning:

- production telemetry, SLO, support, adoption, retention, or incident evidence
  is not measured yet;
- buyer-specific ROI or procurement input is missing;
- `opencode-review`, model review, or reviewer automation is still queued
  without a concrete defect.

No-Go:

- security test or security workflow failure;
- API contract regression;
- document contract mismatch;
- reproducible product defect;
- missing buyer evidence path for the compatibility API, admin evidence
  surface, trace/access-list evidence, readiness endpoint, or commercial
  caveat model;
- Figma Code Connect usage.

## Plugin Responsibilities

| Plugin | Responsibility | Output in this runbook |
|---|---|---|
| Product Design | Convert buyer, operator, compliance, analytics, and procurement review into a concrete acceptance sequence. | Acceptance workflow table and owner mapping. |
| Figma | Visualize the go/no-go workflow in the existing FigJam board. | `KRW 2B Buyer Acceptance Go No Go Workflow`. |
| Superpowers | Keep execution plan, verification commands, and PR update steps explicit. | `docs/superpowers/plans/2026-07-02-commercial-buyer-acceptance-runbook.md`. |
| Ponytail | Reject unnecessary packaging split, dashboard expansion, or dependency addition. | Single repo, single product, no new framework. |
| Data Analytics | Keep measured, repository, Figma, production-proposed, and buyer-specific claims separate. | Metric honesty acceptance step. |

## Final Handoff Checklist

- [ ] Buyer receives `docs/commercial_buyer_diligence_packet.md`.
- [ ] Buyer receives this runbook.
- [ ] Buyer receives `docs/commercial_completion_scorecard.md`.
- [ ] Buyer receives Figma artifact links from `docs/figma_artifacts.md`.
- [ ] Buyer receives the current `/api/v1/commercial_readiness/latest` output.
- [ ] Buyer receives verification output for tests and required security checks.
- [ ] Buyer-specific ROI, support, legal, and deployment inputs are listed as
      follow-up rather than claimed as complete.
