# Releasing

This document is for a human maintainer cutting a real, immutable
`contextual-orchestrator` release. It is deliberately narrow — see
[`docs/planning/adrs/0129-canonical-immutable-release.md`](planning/adrs/0129-canonical-immutable-release.md)
for the full design and its explicit non-goals.

## What a release is, and is not

A release is a git tag `vX.Y.Z` and a GitHub Release built from it. It gives
downstream consumers (Keyverse, BandScope, Wardnet, and others) an immutable,
citable pin target they never again need to vendor a mutable source SHA off
`main` for. Those are two different URLs with two different guarantees:

- `.../releases/tag/vX.Y.Z` is the actual immutable pin — always the same
  commit, forever. **Consumers should pin this one.**
- `.../releases/latest` is a **mutable discovery alias** that repoints to
  whatever the newest release is; it is useful for finding "what's current"
  in a human workflow, but a consumer pinning to it is *not* protected from
  behavior changes across future releases and should not use it as a pin
  target.

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
3. Either no git tag `vX.Y.Z` exists yet, or one does but points at the exact
   commit you're dispatching and has no GitHub Release published yet (a safe
   resume of a run that failed after pushing the tag but before publishing —
   see step 4 below). A tag pointing at any *other* commit, or one whose
   release already exists, is rejected: a tag is never reused or moved onto a
   different commit — bump the version again if you need to re-release.
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
4. Dispatch. The workflow is two jobs, least-privilege: `verify` runs with no
   write permission and no persisted git credential while it executes any
   repository-controlled code; `publish` holds the write token and does
   nothing but tag and publish. In order:
   - **`verify`** (read-only):
     - fails closed if the dispatched commit is not `main`'s current tip (a
       race with a concurrent merge);
     - fails closed if the input version does not match `pyproject.toml`'s
       `[project]` table;
     - resolves any existing `vX.Y.Z` tag via the commit API: fails closed if
       it points at a different commit or its GitHub Release already exists;
       otherwise proceeds (fresh publish, or a safe resume — see step 3
       above);
     - runs the full test suite fresh (`uv run --locked --extra api --extra
       db --extra queue --group dev python -m pytest -q`);
     - renders release notes from `CHANGELOG.md`'s matching section
       (`scripts/ci/release_notes.py`, tested in
       `tests/test_release_notes.py`);
     - best-effort looks up and downloads the CycloneDX SBOM from the
       matching successful `security.yml` run for this commit, if one exists
       (a missing SBOM, or a failed lookup, warns — it never blocks the
       release);
     - uploads the rendered notes and any SBOM for `publish` to pick up.
   - **`publish`** (write-scoped, only after `verify` succeeds):
     - re-verifies `main`'s tip has not advanced while `verify` was testing
       and rendering notes (a second, authoritative check right before
       anything is created);
     - creates and pushes an annotated tag `vX.Y.Z` — skipped when resuming
       a run whose tag already exists at this commit;
     - publishes the GitHub Release using the notes/SBOM `verify` produced.
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
