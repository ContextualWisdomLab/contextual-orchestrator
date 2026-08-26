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

Active ruleset semantics are combined fail-closed: the highest required
approval count applies, and any last-push approval rule excludes the last
pusher from the qualifying reviewer set.

The evaluator is a pure policy boundary. A trusted CI governance collector is
responsible for obtaining the current protected-head, ruleset, checks, review,
and finding evidence. The evaluator returns only machine-readable blocker codes
and non-sensitive counts.

The serving CLI accepts a persisted collector JSON through
`--release-authority-json` only when it carries an HMAC-SHA-256 signature made
with `CONTEXTUAL_ORCHESTRATOR_RELEASE_AUTHORITY_SIGNING_KEY` from the KV
registry. The server verifies the signature with that same non-exported KV
credential before passing the snapshot to protected admin reports. A missing
key, unsigned/malformed snapshot, or changed candidate leaves reports blocked.

## Consequences

- Buyer demonstrations remain inspectable while release authorization is
  honestly blocked until operational evidence exists.
- GitHub governance remains in the central `.github` repository rather than
  being duplicated in the inference runtime.
- A release cannot be approved from a local synthetic merge tree, caller-side
  boolean, or tampered collector JSON that merely says checks passed.

## Customer next action

Use the central protected CI collector for the exact candidate SHA, then provide
its snapshot to `evaluate_release_authorization()` before creating a release.
