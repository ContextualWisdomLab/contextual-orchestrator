# Plugin Visual Directions

These three Product Design directions are comparison material for the Figma
design pass. Direction 1 is the canonical build direction because it follows the
repo's existing `docs/screen_design.md` tokens and enterprise table-first
constraint.

## Direction 1: Evidence Console

This direction keeps the admin console dense, quiet, and operational. It uses a
left navigation rail, a compact top environment bar, and full-width working
sections. The workflow trace sits beside policy and access evidence so reviewers
can answer "why did this happen?" without moving through a visual builder.

Best for:

- compliance and operations review;
- showing route-versus-conduct evidence next to runtime state;
- preserving the stdlib admin console's current visual language.

Tradeoff: it is less visually dramatic than the other options, but it is the
most faithful enterprise control-plane direction.

## Direction 2: Policy Studio

This direction puts policy tuning at the center. It leads with latency-quality
thresholds, mode overrides, replay comparison, and provider exclusion controls.
Workflow traces become supporting evidence below the policy workspace.

Best for:

- AI product owners who tune orchestration policy;
- product reviews where the main question is whether to route fast or conduct
  deeply;
- future learned-routing evaluation discussions.

Tradeoff: it risks making policy editing look more important than auditability,
which conflicts with the current MVP priority unless the product owner audience
is dominant.

## Direction 3: Audit Timeline

This direction treats each run as an auditable event. The primary view is a
timeline of thinker, worker, verifier, and synthesizer steps with access-list
and provider-exclusion evidence attached to each step.

Best for:

- compliance reviewers;
- incident review and support handoff;
- explaining Conductor-style access visibility.

Tradeoff: it makes a single workflow very clear, but it is weaker for daily
pool management and policy scanning.

## Canonical Selection

Use Direction 1 for the main editable Figma frames. Include Directions 2 and 3
as visual alternatives in the same Figma file or stakeholder deck, but do not
let them add MVP surfaces that are absent from the product plan.

## Image Generation Brief

All three generated visual options should use desktop dashboard dimensions
`1440 x 1024`, avoid nested cards, keep enterprise control density, and make the
actual orchestration evidence visible in the first viewport.
