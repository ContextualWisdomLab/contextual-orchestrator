# ADR 0020: Separate product evidence from release authorization

- Status: Accepted
- Date: 2026-08-20
- Figma design file: `vsZMd8WAv42HDRgcZuNcWk`
- FigJam board: `Wr8iMlB9SHkerHSjv0Pe0M`

## Decision

The commercial release-candidate report exposes local product evidence and a
separate fail-closed release-authority result. It never treats a missing,
queued, stale, synthetic, predecessor-head, author-only, or unresolved-finding
snapshot as release-ready.

The evaluator is a pure policy boundary. A trusted CI governance collector is
responsible for obtaining the current protected-head, ruleset, checks, review,
and finding evidence. The evaluator returns only machine-readable blocker codes
and non-sensitive counts.

The serving CLI accepts the persisted collector JSON through
`--release-authority-json` and passes it to the protected admin reports. A
missing file or malformed snapshot leaves the reports blocked; a changed
candidate requires a newly collected exact-head file.

## Consequences

- Buyer demonstrations remain inspectable while release authorization is
  honestly blocked until operational evidence exists.
- GitHub governance remains in the central `.github` repository rather than
  being duplicated in the inference runtime.
- A release cannot be approved from a local synthetic merge tree or caller-side
  boolean that merely says checks passed.

## Customer next action

Use the central protected CI collector for the exact candidate SHA, then provide
its snapshot to `evaluate_release_authorization()` before creating a release.
