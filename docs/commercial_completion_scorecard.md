# Commercial Completion Scorecard

This scorecard defines what Figma, Product Design, Superpowers, Ponytail, and
Data Analytics can do to make Contextual Orchestrator reviewable for a KRW
2,000,000,000 enterprise sale.

Scope phrase: KRW 2,000,000,000 enterprise sale.

The target is buyer due-diligence readiness. It is not guaranteed revenue,
valuation, purchase approval, or a production compliance certificate. Figma Code
Connect is not used.

## Scorecard Summary

| Area | Completion evidence | Status rule | Blocker rule |
|---|---|---|---|
| Product Design | Buyer, operator, security/compliance, and procurement workflows are mapped to admin surfaces and readiness endpoints. | Ready when every persona has an evidence path. | Block only if a required buyer evidence path is missing from product/API/docs. |
| Figma | Editable admin design, FigJam diagrams, and stakeholder deck exist without Code Connect. | Ready when artifacts are recorded in `docs/figma_artifacts.md`. | Block only if artifact evidence is missing or Code Connect is introduced. |
| Superpowers | A dated TDD plan describes files, commands, expected failures, and final verification. | Ready when the plan links docs, tests, and PR validation. | Block only if verification commands are absent or failing. |
| Ponytail | Single-repo product is retained; library/submodule split is deferred until explicit extraction triggers exist. | Ready when no new dependency or split is introduced for this increment. | Block only if packaging creates avoidable review, release, or provenance overhead. |
| Data Analytics | Measured local evidence and proposed production or buyer-specific KPIs are separated. | Ready when each KPI has an evidence type. | Block only if measured and proposed claims are mixed. |

Review process is not a blocker. Review delay, model-review delay, or queued
review automation is not a product blocker unless it reports a concrete
security, contract, or functional defect.

## Plugin Completion Criteria

### Product Design

Can do:

- turn the KRW 2,000,000,000 target into buyer-review personas;
- define workflows for economic buyer, platform operator, security/compliance,
  and procurement reviewer;
- map each workflow to `/admin`, `/api/v1/commercial_readiness/latest`,
  `/api/v1/analytics_snapshots/latest`, workflow traces, and access reports;
- define QA criteria for bilingual operator copy and evidence visibility.

Completion criteria:

- `docs/plugin_driven_design_brief.md` includes commercial readiness scope;
- `docs/commercial_plugin_operating_model.md` lists personas, workflows, and
  screen priorities;
- `/admin` exposes commercial readiness status and remediation.

### Figma

Can do:

- maintain editable screen artifacts for the admin evidence control plane;
- maintain FigJam diagrams for commercial readiness flow, library split
  decision, and scorecard relationships;
- generate stakeholder-ready slides for a KRW 2,000,000,000 review.

Completion criteria:

- `docs/figma_artifacts.md` records `KRW 2B Commercial Readiness Flow`;
- `docs/figma_artifacts.md` records `Library Split Decision For KRW 2B Sale`;
- `docs/figma_artifacts.md` records `KRW 2B Completion Scorecard`;
- Figma Code Connect is not used.

### Superpowers

Can do:

- convert the plan into task-by-task execution;
- require TDD and contract tests before documentation claims are accepted;
- keep the final verification commands visible.

Completion criteria:

- `docs/superpowers/plans/2026-07-02-commercial-plugin-readiness.md` exists;
- the plan includes `python tests/test_plugin_driven_artifacts.py`,
  `python -m compileall contextual_orchestrator tests`, `pytest -q`, and
  `git diff --check`;
- PR evidence is updated after push.

### Ponytail

Can do:

- decide whether to keep one repo, split a library, or use a submodule;
- reject unnecessary split work when it does not improve buyer due diligence;
- document future extraction triggers.

Decision:

- Keep one repository and one deployable product for this increment.
- Do not create a separate library, Git submodule, or extracted package now.

Extraction triggers:

- a second product needs the orchestration core without the admin evidence
  control plane;
- the core needs independent semantic versioning;
- security provenance requires a separately locked package.

### Data Analytics

Can do:

- define commercial KPIs;
- separate measured local evidence from production or buyer-specific proposals;
- attach GitHub/CI maturity evidence.

Measured local evidence:

- `commercial_readiness_pass_rate`;
- `buyer_evidence_completeness`;
- `security_control_pass_rate`;
- `trace_audit_completeness`;
- CodeQL, Dependency review, Python supply chain, Trivy, Trivy filesystem,
  coverage-evidence, scan-pr-queue, and Strix status.

Proposed until production:

- `support_operability_score`;
- production adoption, latency, SLO, incident, and support evidence.

Proposed until buyer-specific:

- `roi_evidence_status`;
- procurement ROI model;
- customer-specific legal and security questionnaire evidence.

## Final Completion Gate

Ready:

- `commercial_readiness_report(target_contract_value_krw=2000000000)` returns
  no failures for local due-diligence evidence;
- documentation and Figma artifacts describe the buyer evidence path;
- full tests pass.

Warning:

- production telemetry, SLO, support, or buyer-specific ROI evidence remains
  proposed rather than measured.

Blocked:

- security test failure;
- API or document contract mismatch;
- reproducible product defect;
- Figma Code Connect usage.
