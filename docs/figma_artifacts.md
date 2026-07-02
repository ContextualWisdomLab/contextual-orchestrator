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
