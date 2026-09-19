# Commercial Plugin Operating Model

This plan defines what Figma, Product Design, Superpowers, Ponytail, and Data
Analytics can do to make Contextual Orchestrator reviewable for a KRW
2,000,000,000 enterprise sale. The target is buyer due-diligence readiness, not
guaranteed revenue, valuation, purchase commitment, or compliance
certification.

Figma Code Connect is not used.

## Completion Standard

The program is commercially complete when a buyer can review one evidence packet
covering:

- compatible API adoption through `/v1/chat/completions`;
- admin control-plane evidence through `/admin` and `/admin/state`;
- source-backed local analytics through `/api/v1/analytics_snapshots/latest`;
- sales readiness through `/api/v1/sales_readiness/latest`;
- KRW 2,000,000,000 commercial readiness through
  `/api/v1/commercial_readiness/latest`;
- security, provider egress, trace audit, access-list, evaluation replay, and
  English/Korean locale evidence;
- documented caveats separating measured local evidence from proposed
  production or buyer-specific claims.

Review process is not a blocker. A blocker must be a security test failure,
contract/API mismatch, or reproducible product defect.

## Plugin Workstreams

| Plugin | What it can do | Concrete output |
|---|---|---|
| Figma | Create editable review artifacts without Code Connect. | Commercial readiness deck, KRW 2B commercial flow, library split decision tree, admin readiness frame backlog. |
| Product Design | Convert the price target into buyer review workflows. | Persona/workflow/screen-priority model for buyer, operator, compliance, and procurement reviews. |
| Superpowers | Turn the plan into execution steps and verification gates. | Dated plan in `docs/superpowers/plans/2026-07-02-commercial-plugin-readiness.md`. |
| Ponytail | Prevent unnecessary artifacts and premature extraction. | Decision to keep one repo and one deployable product until explicit extraction triggers exist. |
| Data Analytics | Separate measured evidence from proposed KPIs. | Commercial KPI model and GitHub/CI maturity evidence in `docs/analytics_spec.md`. |

## Product Design Plan

Primary review personas:

- Economic buyer: checks whether the KRW 2,000,000,000 value case is supported
  by API compatibility, evidence control, replay, and auditability.
- Platform operator: checks agent health, routing policy, capacity, provider
  exclusions, and runtime evidence.
- Security and compliance reviewer: checks authentication, trace exposure,
  provider egress, access-list visibility, and audit exceptions.
- Procurement reviewer: checks readiness caveats, support ownership, security
  evidence, and what remains external to the repository.

Required workflows:

1. Buyer opens the stakeholder deck and confirms the commercial readiness
   definition is not a valuation guarantee.
2. Operator opens `/admin` and reviews sales/commercial readiness summaries.
3. Compliance reviewer opens workflow traces and access reports.
4. Product owner reviews local analytics and separates measured values from
   proposed production KPIs.
5. Procurement reviewer checks `docs/commercial_readiness.md`,
   `docs/library_research.md`, and this operating model.

Screen priorities:

1. Commercial Readiness Overview
2. Buyer Evidence Packet
3. Security And Access Control
4. Workflow Trace And Access Report
5. Analytics Evidence And KPI Caveats
6. Packaging Decision
7. Locale Review

## Figma Plan

Existing artifacts remain the durable design surfaces:

- Figma design file: `https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk`
- FigJam board: `https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M`
- Figma Slides deck: `Contextual Orchestrator KRW 2B Commercial Readiness Plan`

Added FigJam diagrams:

- `KRW 2B Commercial Readiness Flow`
- `Library Split Decision For KRW 2B Sale`

The next Figma design update should add editable frames for:

- `09 Commercial Readiness Overview`
- `10 Buyer Evidence Packet`
- `11 Packaging Decision`
- `12 Analytics Evidence Caveats`

## Ponytail Packaging Decision

Current decision: keep one repository and one deployable product.

Do not create a separate library, Git submodule, or extracted package for this
commercial-readiness increment.

Rationale:

- The buyer value is the integrated evidence surface, not a standalone
  orchestration package.
- A submodule would add procurement and security review overhead.
- A package split would create versioning and release obligations before there
  is a second consumer.

Extraction triggers:

- A second product needs the orchestration core without the admin evidence
  control plane.
- The core needs independent semantic versioning and compatibility guarantees.
- Security provenance review requires a separately locked package.

## Data Analytics Plan

Measured local evidence:

- `commercial_readiness_pass_rate`
- `buyer_evidence_completeness`
- `security_control_pass_rate`
- `trace_audit_completeness`
- GitHub/CI status for CodeQL, Dependency review, Python supply chain, Trivy,
  Trivy filesystem, coverage-evidence, scan-pr-queue, and Strix.

Proposed until production:

- `support_operability_score`
- production adoption and retention KPIs;
- production SLO and incident response evidence.

Evidence label: proposed until production.

Proposed until buyer-specific:

- `roi_evidence_status`;
- procurement ROI model;
- customer-specific data processing and security questionnaire evidence.

Evidence label: proposed until buyer-specific.

## Superpowers Execution Loop

1. Add or update contract tests before changing documentation.
2. Update Product Design, Figma, Ponytail, and Data Analytics evidence docs.
3. Run `python tests/test_plugin_driven_artifacts.py`.
4. Run `python -m compileall contextual_orchestrator tests`.
5. Run `pytest -q`.
6. Run `git diff --check`.
7. Push to PR and classify only concrete security, contract, or functional
   defects as blockers.

## Acceptance Criteria

- Figma Code Connect is not used.
- The KRW 2,000,000,000 target is described only as due-diligence readiness.
- Library/submodule separation is explicitly rejected for this increment.
- Extraction triggers are documented.
- Measured and proposed Data Analytics metrics are separated.
- Review process is not a blocker.
- `tests/test_plugin_driven_artifacts.py` and full `pytest -q` pass.
