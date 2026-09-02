# Releasing

This document is for a human maintainer cutting a real, immutable
`contextual-orchestrator` release. It is deliberately narrow — see
[`docs/planning/adrs/0127-canonical-immutable-release.md`](planning/adrs/0127-canonical-immutable-release.md)
for the full design and its explicit non-goals.

## What a release is, and is not

A release is a git tag `vX.Y.Z` and a GitHub Release built from it. It gives
downstream consumers (Keyverse, BandScope, Wardnet, and others) an immutable,
citable pin target — `.../releases/latest` and `.../releases/tag/vX.Y.Z` — so
they never again need to vendor a mutable source SHA off `main`.

A release is **not** the same thing as
[`/api/v1/commercial_release_candidates/latest`](commercial_release_candidate.md)
or `contextual_orchestrator/release_authorization.py`. Those answer "is this
pull request commercially/buyer-sale-ready" for a human procurement audience,
gated behind admin auth inside the running gateway. This document's release
mechanism answers a narrower question — "does an immutable, citable artifact
exist for this exact commit" — and is unaffected by, and does not affect,
that separate system.

## Preconditions

1. The version to release is already merged to `main`: `pyproject.toml`'s
   `version` field carries the exact `X.Y.Z` you intend to release, landed
   through the normal PR process (review, required checks, no exceptions).
2. `CHANGELOG.md` has a `## [X.Y.Z]` section (an `- Unreleased` or dated
   suffix is fine) with real, non-empty content describing what changed.
3. No git tag `vX.Y.Z` already exists (`git tag -l | grep vX.Y.Z` locally, or
   check <https://github.com/ContextualWisdomLab/contextual-orchestrator/tags>).
   A tag is never reused or moved onto a different commit — bump the version
   again if you need to re-release.
4. `main` is currently green — its own required checks (Tests, Security,
   Fuzz, and the org-central Strix/OpenCode/security-scan/OSV/Scorecard
   checks from `ContextualWisdomLab/.github`) are passing. The release
   workflow re-verifies the commit is genuinely `main`'s untampered tip and
   re-runs the full test suite fresh, but it does not re-run CodeQL, Trivy,
   OSV, Scorecard, or the review bots — those already had to pass before this
   commit could exist on protected `main` at all.

## Cutting a release

1. Go to **Actions → Release → Run workflow** in the GitHub UI (or
   `gh workflow run release.yml -f version=X.Y.Z`).
2. Select branch `main` (the workflow refuses to run against anything else).
3. Enter the exact version, e.g. `0.2.0` — no leading `v`, must match
   `pyproject.toml` byte-for-byte.
4. Dispatch. The workflow, in order:
   - fails closed if the dispatched commit is not `main`'s current tip (a
     race with a concurrent merge);
   - fails closed if the input version does not match `pyproject.toml`;
   - fails closed if the tag already exists, locally or on `origin`;
   - runs the full test suite fresh (`uv run --locked --extra api --extra db
     --extra queue --group dev python -m pytest -q`);
   - renders release notes from `CHANGELOG.md`'s matching section
     (`scripts/ci/release_notes.py`, tested in
     `tests/test_release_notes.py`);
   - creates and pushes an annotated tag `vX.Y.Z`;
   - best-effort attaches the CycloneDX SBOM from the matching successful
     `security.yml` run for this commit, if one exists (a missing SBOM warns,
     it never blocks the release);
   - publishes the GitHub Release.
5. Confirm at
   <https://github.com/ContextualWisdomLab/contextual-orchestrator/releases/latest>.

## After a release

- Bump `pyproject.toml`'s `version` and open a new `## [next-version] -
  Unreleased` `CHANGELOG.md` section in an ordinary PR, so the repository is
  never left claiming to already be the version it just released.
- Downstream consumers with an open handoff on this gap
  (`ContextualWisdomLab/keyverse#132`, `ContextualWisdomLab/bandscope#881`,
  the Wardnet consumer-owner handoff on `contextual-orchestrator#971`) can
  now bump to the published tag instead of a vendored source SHA.

## Rollback

Releases are immutable — never delete or retag a published release to "fix"
it. If a released commit turns out to be broken, release a new patch/minor
version with the fix through the same process above. `gh release delete
vX.Y.Z` (and its tag) is reserved for a genuine publishing mistake caught
immediately after dispatch, before any consumer could plausibly have pinned
it, and should still be treated as an exceptional, logged action, not routine
practice.
