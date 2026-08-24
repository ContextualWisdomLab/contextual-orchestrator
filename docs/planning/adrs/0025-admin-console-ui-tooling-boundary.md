---
id: "0025"
title: "Keep the admin console inline stdlib HTML; defer Storybook/component tooling"
status: accepted
proposed_date: "2026-08-23"
accepted_date: "2026-08-23"
deciders:
  - "repository maintainer"
consulted:
  - "docs/code_conventions.md (dependency-free runtime rationale)"
informed:
  - "downstream consumers evaluating the /admin console"
affected_components:
  - "contextual_orchestrator/admin.py"
  - "docs/figma_artifacts.md"
  - "docs/product-technical-gap-baseline.md"
effort: S
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0023-product-technical-gap-baseline.md"
    relation: informational
asr_triggers:
  - kind: process
    evidence: "The standing operating instructions for this repository require Figma, Storybook, ui-ux-pro-max, and Anti-Slop-UI for any UI work, with the Figma File ID recorded in an ADR either way (adopt or explicitly decline with a stated why). No dedicated ADR existed; the decision only lived as prose inside the gap-baseline document."
    note: "A decision repeated only in a living status document is easy to lose on the document's next major edit; an ADR is the durable record."
success_criteria:
  - metric: "existence of a standalone, citable design-tooling decision record"
    target: "one ADR states the current admin-console UI scope, the Figma file it is grounded in, and the explicit trigger for introducing Storybook/component tooling"
    measurement_window: "reviewed whenever admin.py grows a second screen family or a second consuming frontend appears"
    source: "this document"
---

# Keep the admin console inline stdlib HTML; defer Storybook/component tooling

## Context

`contextual_orchestrator/admin.py` is the entire `/admin` operator console:
inline HTML, CSS, and JavaScript strings served by the stdlib HTTP handler in
`server.py`. `CLAUDE.md` documents this as deliberate — the console "stays
inline while the product is dependency-free," matching the repository's
broader stdlib-only runtime rationale (`docs/code_conventions.md`,
`conductor/tech-stack.md`).

The organization's standing UI/UX operating instructions require, for any UI
work: Figma for visual design, Storybook (<https://github.com/storybookjs/storybook>)
for component/scene/edge-case inventory, the `ui-ux-pro-max` skill, and
`Anti-Slop-UI` review, with design tokens for repeated web objects and a
Figma File ID recorded in an ADR. An editable Figma design file already
exists for this console — `Contextual Orchestrator Plugin-Driven Admin
Design`, file ID `vsZMd8WAv42HDRgcZuNcWk`
(<https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk>), recorded in
`docs/figma_artifacts.md` with eight frames covering the overview dashboard,
agent pool, orchestration policy, workflow-run trace, access report,
evaluation replay, locale review, and a visual-directions comparison. What
was missing was a standalone decision record for the Storybook/component-
tooling half of that instruction — it existed only as one sentence inside the
living `docs/product-technical-gap-baseline.md`, which is explicitly a dated
snapshot, not a durable design decision.

## Decision Drivers

* Honor the organization's UI-tooling instruction (Figma cited, Storybook
  considered, decision recorded in an ADR) without silently skipping it.
* Do not import a Node/React/Storybook toolchain into a repository whose
  entire runtime dependency surface is the Python standard library, purely
  to satisfy a process checklist — that would violate this repository's own
  Ponytail design gate (`docs/library_research.md`: no new dependency when
  the existing approach covers the need).
* Keep the trigger for revisiting this decision concrete and observable,
  not a vague "someday," so the deferral does not become permanent by
  default.

## Considered Options

* Introduce Storybook now against the existing inline HTML/CSS/JS strings in
  `admin.py`, wrapping each screen as a "story" for edge-case review.
* Defer Storybook/component tooling until a second consumer of the same UI
  primitives exists, and record why in an ADR now.
* Rewrite `admin.py` as a component-based frontend (React/Vue + build step)
  specifically to make Storybook adoption straightforward.

## Decision Outcome

Chosen option: "Defer Storybook/component tooling; record the trigger for
revisiting this in an ADR now."

| Driver | Storybook now | Defer, ADR now | Rewrite as component frontend |
| --- | --- | --- | --- |
| Matches stdlib-only runtime philosophy | No — Storybook requires Node/npm and a component framework | Yes | No |
| Satisfies the "record in an ADR" instruction | Only if written up separately anyway | Yes | Only if written up separately anyway |
| Avoids speculative infrastructure for one console with no second consumer | No | Yes | No |
| Effort proportional to current need (one operator console, one repository) | No | Yes | No |

Storybook, `ui-ux-pro-max`, and `Anti-Slop-UI` are the right tools when this
repository (or a consuming repository, e.g. LineageWeave) ships a
component-based frontend with reusable, composable UI primitives across more
than one screen family or more than one product surface. `admin.py`'s eight
screens are one inline HTML document each, hand-styled against the existing
Figma frames; there is no component library to catalog and no second
consumer reusing these primitives today. Introducing a Node toolchain here
would add exactly the kind of unrequested dependency and process weight this
repository's Ponytail gate exists to prevent, for a checklist item rather
than a real gap.

**Explicit trigger to revisit this decision** (any one of the following
makes the deferral obsolete and Storybook adoption the correct next step,
not optional):

1. `admin.py` grows a second distinct screen family reusing the same visual
   primitives (buttons, tables, forms, charts) across more than the current
   eight Figma-grounded frames, making "design tokens + modularization for
   repeated web objects" a real, not speculative, requirement.
2. A second repository (e.g. LineageWeave, a naruon-facing surface) adopts
   this console's component patterns as a shared frontend package.
3. This repository itself adds a component-based frontend for any other
   reason (a customer-facing UI, not just the operator console).

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| The Storybook/UI-tooling decision for `admin.py` existed only as prose inside a dated status snapshot (`docs/product-technical-gap-baseline.md`), not a durable ADR. | Record the decision, its drivers, and its explicit revisit trigger in a standalone ADR. | Implemented in this document |
| The existing Figma File ID was recorded in `docs/figma_artifacts.md` but not cross-referenced from a UI-tooling ADR. | Cite the Figma File ID here explicitly. | Implemented in this document |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| The deferral is read as a permanent "no" rather than a conditional one, and a future genuine multi-screen-family need gets built without Storybook out of habit. | low | medium | The three explicit revisit triggers above are concrete and checkable against `admin.py`'s actual screen inventory; any of them being met is itself the signal to reopen this ADR. | maintainer |
| A future contributor adds a Node/Storybook dependency to satisfy the process checklist without a real second consumer, adding build-toolchain weight to a stdlib-only repository for no functional gain. | low | low | This ADR's Decision Outcome and Ponytail-gate rationale are the citable reason to decline that PR unless a trigger condition is actually met. | maintainer |

## Rollback / Exit Strategy

None required — this ADR changes no code or dependencies. If any revisit
trigger is met, the exit path is additive: introduce Storybook against the
existing Figma frames and `admin.py` screens without needing to revert this
decision, since it was never a code change.

## Affected Components

* contextual_orchestrator/admin.py (scope reference only — no change)
* docs/figma_artifacts.md
* docs/product-technical-gap-baseline.md
* docs/planning/adrs/0025-admin-console-ui-tooling-boundary.md

## More Information

* Figma design file: `Contextual Orchestrator Plugin-Driven Admin Design`,
  file ID `vsZMd8WAv42HDRgcZuNcWk`
  (<https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk>).
* `docs/figma_artifacts.md` (frame inventory and FigJam architecture board).
* `docs/code_conventions.md` and `conductor/tech-stack.md` (stdlib-only
  runtime rationale this decision is consistent with).
* Storybook (<https://github.com/storybookjs/storybook>), `ui-ux-pro-max`
  (<https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>), and
  `Anti-Slop-UI` (<https://github.com/local-over/Anti-Slop-UI>) remain the
  designated tools for the trigger conditions above, not rejected outright.
