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

The first access-list diagram render accepted multiline labels, but the clean
single-line version above is the artifact to use for review.

## Stakeholder Deck

Name: `Contextual Orchestrator Plugin-Driven Product Plan`

Delivery: generated as a Figma Slides deck and displayed through the Figma
Slides preview widget in this run.

Purpose: concise stakeholder review of product thesis, plugin workstreams,
three visual directions, canonical Evidence Console selection, architecture
diagrams, analytics model, and implementation path.

## Product Design Image Directions

Generated image files:

- Evidence Console:
  `/Users/seonghobae/.codex/generated_images/019f1ffa-f314-7181-9432-ee9b0e993131/ig_0711874b766cb6ca016a45a25dfc7081918dd584595c7abdb2.png`
- Policy Studio:
  `/Users/seonghobae/.codex/generated_images/019f1ffa-f314-7181-9432-ee9b0e993131/ig_0711874b766cb6ca016a45a2e990f08191a8f12d24a1fd7793.png`
- Audit Timeline:
  `/Users/seonghobae/.codex/generated_images/019f1ffa-f314-7181-9432-ee9b0e993131/ig_0711874b766cb6ca016a45a33671908191bbb489f4dc158c1c.png`

These images are comparison material. The editable Figma frames use Evidence
Console as the canonical direction.

## Code Connect Exclusion

Figma Code Connect was not used for discovery, metadata, code generation, or
artifact creation. The editable design file was created with Figma Plugin API
operations from repo docs and product constraints.
