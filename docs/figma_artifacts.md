# Figma Artifacts

## Editable Design File

Name: `Contextual Orchestrator Plugin-Driven Admin Design`

URL: https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk

Purpose: editable admin-console screen set grounded in `docs/screen_design.md`,
`docs/product_planning.md`, `docs/rest_api_design.md`, and
`docs/i18n_design.md`.

Frames created:

- `01 Overview Dashboard / Evidence Console`
- `02 Agent Pool`
- `03 Orchestration Policy`
- `04 Workflow Run Trace`
- `05 Access Report`
- `06 Evaluation Replay`
- `07 Locale Review`
- `08 Visual Directions Comparison`

Validation performed:

- The design file contains eight editable `1440 x 1024` frames.
- Frame text includes `agent_pools`, `workflow_runs`, `access_reports`,
  `evaluation_runs`, and `locale_bundles`.
- Korean locale text is present in the locale-review frame.
- One overview screenshot was inspected after fixing a clipped policy-table row.

## FigJam Board

Name: `Contextual Orchestrator Architecture`

URL: https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M

Diagrams created:

- `Contextual Orchestrator Architecture`
- `Route Versus Conduct Flow`
- `Workflow Trace And Access Lists Clean`
- `API And Control Plane Relationship`
- `KRW 2B Commercial Readiness Flow`
- `Library Split Decision For KRW 2B Sale`
- `KRW 2B Completion Scorecard`
- `KRW 2B Buyer Deal Room Evidence Matrix`
- `KRW 2B Buyer Acceptance Go No Go Workflow`
- `KRW 2B Buyer Evidence Manifest Workflow`
- `KRW 2B Runtime Buyer Evidence Endpoint`
- `KRW 2B Buyer Handoff Bundle Workflow`
- `KRW 2B Saleability Decision Gate`
- `KRW 2B Commercial Evidence Export`
- `KRW 2B Commercial Acceptance Check`
- `KRW 2B Commercial Release Candidate`
- `KRW 2B Commercial Gap Register`
- `KRW 2B Commercial Procurement Readiness`

The first access-list diagram render accepted multiline labels, but the clean
single-line version above is the artifact to use for review.

The KRW 2B commercial readiness flow maps enterprise buyer review to product
capability evidence, security and access control, operations and support
readiness, measured analytics evidence, proposed production KPIs, and the
`commercial_readiness_report` decision.

The library split decision tree records the Ponytail packaging decision: keep a
single repository now, and only extract a library or submodule when there is a
second product, independent release cadence, or security provenance trigger.

The completion scorecard diagram maps Figma, Product Design, Superpowers,
Ponytail, and Data Analytics outputs to ready, warning, and blocker states for
the KRW 2,000,000,000 due-diligence gate.

The buyer deal-room evidence matrix maps buyer questions to product evidence,
commercial evidence, governance evidence, and evidence type labels:
`measured_local`, `repository_artifact`, `figma_artifact`,
`proposed_until_production`, and `proposed_until_buyer_specific`.

The buyer acceptance go/no-go workflow maps the evidence packet, acceptance
checks, and decision states that determine whether a KRW 2,000,000,000 buyer
review is ready, ready with caveats, buyer-specific follow-up, or blocked by a
concrete defect.

The buyer evidence manifest workflow maps the single review index from scope
and caveats through runtime endpoints, repository documents, Figma artifacts,
verification commands, and buyer-specific follow-ups into ready evidence,
caveat evidence, or concrete-defect handling.

The runtime buyer evidence endpoint workflow maps analytics, sales readiness,
commercial readiness, repository documents, verification commands, Figma
artifacts, and packaging decisions into `/api/v1/buyer_evidence_manifests/latest`
so buyer review evidence is available as both documentation and runtime JSON.

The buyer handoff bundle workflow maps runtime reports, repository packet,
Figma stakeholder artifacts, verification commands, packaging decision,
production follow-up, buyer-specific follow-up, and concrete-defect handling
into `/api/v1/buyer_handoff_bundles/latest`.

The saleability decision gate maps `/api/v1/buyer_handoff_bundles/latest`,
concrete blocker detection, review-process non-blocker policy, warning
follow-ups, and ready or blocked saleability states into
`/api/v1/saleability_decisions/latest`.

The commercial evidence export workflow maps `/api/v1/saleability_decisions/latest`,
runtime reports, buyer packet documents, Figma stakeholder artifacts,
verification commands, review-process non-blocker policy, packaging decision,
and required external evidence gaps into
`/api/v1/commercial_evidence_exports/latest`.

The commercial acceptance check workflow maps `/api/v1/commercial_evidence_exports/latest`,
runtime endpoint chain, buyer packet documents, admin operator surface,
verification evidence, Figma stakeholder artifacts, review-process non-blocker
policy, packaging decision, and external evidence gaps into
`/api/v1/commercial_acceptance_checks/latest`.

The commercial release candidate workflow maps the commercial acceptance check,
runtime endpoint chain, repository distribution packet, security metadata,
admin operator surface, verification tests, Figma stakeholder artifacts,
review-process non-blocker policy, packaging decision, and external release
gaps into `/api/v1/commercial_release_candidates/latest`.

The commercial gap register workflow maps release-candidate external gaps into
production input, buyer input, owner assignment, required input, concrete
blocker handling, and clear/open/blocked register states exposed through
`/api/v1/commercial_gap_registers/latest`.

The commercial procurement readiness workflow maps the gap register, local
packet evidence, license and rights, security metadata, distribution docs,
admin evidence, production input, buyer input, review-process policy, and
packaging decision into `/api/v1/commercial_procurement_readiness/latest`.

The commercial contract readiness workflow `KRW 2B Commercial Contract Readiness`
maps procurement readiness, support and SLO terms, security and
privacy terms, audit/export obligations, license and commercial rights, buyer
order-form input, review-process policy, and packaging decision into
`/api/v1/commercial_contract_readiness/latest`.

The commercial onboarding readiness workflow `KRW 2B Commercial Onboarding Readiness`
maps contract readiness, buyer kickoff, support/SLO action, buyer order-form
action, telemetry capture, acceptance exit criteria, security/legal handoff,
review-process policy, and packaging decision into
`/api/v1/commercial_onboarding_readiness/latest`.

The commercial operations readiness workflow `KRW 2B Commercial Operations Readiness`
maps onboarding readiness, deployment runbook, monitoring/telemetry capture,
incident and rollback plan, backup/recovery evidence, support/SLO ownership,
security/legal handoff, review-process policy, and packaging decision into
`/api/v1/commercial_operations_readiness/latest`.

The commercial security attestation workflow
`KRW 2B Commercial Security Attestation` maps operations readiness, security
policy, dependency lock/package metadata, security workflow metadata, runtime
access-control profile, audit/export evidence, vulnerability scan evidence,
third-party attestation or penetration-test evidence, buyer privacy/DPA input,
review-process policy, and packaging decision into
`/api/v1/commercial_security_attestations/latest`.

The commercial value readiness workflow `KRW 2B Commercial Value Readiness`
maps commercial readiness, evidence export, security attestation, local
analytics evidence, pricing/package rationale, ROI model inputs, reference
customer proof, procurement budget owner, implementation payback assumptions,
review-process policy, and packaging decision into
`/api/v1/commercial_value_readiness/latest`.

## Stakeholder Deck

Name: `Contextual Orchestrator Plugin-Driven Product Plan`

Delivery: generated as a Figma Slides deck and displayed through the Figma
Slides preview widget in this run.

Purpose: concise stakeholder review of product thesis, plugin workstreams,
three visual directions, canonical Evidence Console selection, architecture
diagrams, analytics model, and implementation path.

Commercial-readiness deck:

- Name: `Contextual Orchestrator KRW 2B Commercial Readiness Plan`
- Delivery: generated as a Figma Slides deck through the Figma deck tool after
  resolving the Figma plan key `team::1408252278989737675`.
- Purpose: explain the KRW 2,000,000,000 buyer due-diligence standard, plugin
  workstreams, evidence model, packaging decision, and execution plan.
- Caveat: the deck frames KRW 2,000,000,000 as due-diligence readiness, not a
  valuation guarantee, purchase commitment, or production compliance
  certificate.

## Product Design Image Directions

Three Product Design image directions were generated during the execution run:

- Evidence Console
- Policy Studio
- Audit Timeline

The image files are local execution artifacts and are not committed to this
repository. The editable Figma frames use Evidence Console as the canonical
direction, so the durable review source is the Figma design file above.

## Code Connect Exclusion

Figma Code Connect was not used for discovery, metadata, code generation, or
artifact creation. The editable design file was created with Figma Plugin API
operations from repo docs and product constraints.
