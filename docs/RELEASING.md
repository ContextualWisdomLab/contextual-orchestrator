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
   commit you're dispatching — in which case the workflow safely resumes
   instead of re-tagging: if that tag has no GitHub Release published yet,
   it creates one; if the Release also already exists (e.g. a prior run's
   asset-upload step failed after `gh release create` itself succeeded), it
   still attempts the best-effort SBOM asset attach rather than treating the
   run as nothing left to do — see step 4 below. A tag pointing at any
   *other* commit is rejected outright: a tag is never reused or moved onto
   a different commit — bump the version again if you need to re-release.
4. `main` is currently green — its own required checks (Tests, Security,
   Fuzz, and the org-central Strix/OpenCode/security-scan/OSV/Scorecard
   checks from `ContextualWisdomLab/.github`) are passing. The release
   workflow re-verifies both automatically: the commit is genuinely `main`'s
   untampered tip, and every check GitHub reports for that exact commit
   (excluding the release run's own) is complete with a successful,
   skipped, or neutral conclusion — it fails closed otherwise. It also
   re-runs the full test suite fresh, but it does not re-run CodeQL, Trivy,
   OSV, Scorecard, or the review bots — those already had to pass before this
   commit could exist on protected `main` at all.
   - **If you dispatch moments after a merge lands**, the gate can fail
     with "expected push-triggered check(s) ... have not registered yet" —
     GitHub has not finished creating this new tip's Tests/Security/Fuzz
     check-run entries yet. This is expected and safe: wait a few moments
     for those workflows to actually start, then re-dispatch. It is
     distinct from a genuine pending/failed check, which the same gate
     reports as "not both complete and green" instead.

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
     - fails closed unless every one of this repository's own known
       push-triggered checks (Tests' two jobs, Fuzz's two jobs, Security's
       two jobs — see `RELEASE_EXPECTED_PUSH_CHECKS` in `release.yml`) has
       actually registered as a check-run for this exact commit *and* every
       check GitHub reports for it is complete with a successful, skipped,
       or neutral conclusion (a push-triggered workflow — Security, Fuzz,
       ... — not yet registered, still running, or having failed on this
       commit);
     - fails closed if the input version does not match `pyproject.toml`'s
       `[project]` table;
     - resolves any existing `vX.Y.Z` tag via the commit API: fails closed
       only if it points at a *different* commit; a tag at this commit
       proceeds as a resume (fresh publish, tag-only resume, or full
       release-and-asset resume — see step 3 above). A failed tag or
       Release lookup is treated as "absent" only on a *confirmed* 404 /
       "release not found"; any other lookup failure (rate limit, auth,
       network, 5xx) fails this step closed instead of guessing — re-dispatch
       once the transient failure clears;
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
     - re-verifies `main`'s tip has not advanced, and every check for this
       commit is still complete and green, while `verify` was testing and
       rendering notes (a second, authoritative recheck of both, right
       before anything is created — see "Known limitations" below for the
       small residual window this still leaves);
     - creates and pushes an annotated tag `vX.Y.Z` — skipped when resuming
       a run whose tag already exists at this commit;
     - creates the GitHub Release using the notes `verify` produced —
       skipped when resuming a run whose Release already exists at this
       commit;
     - attempts the best-effort SBOM asset attach, whether the Release was
       just created or already existed — a failure here warns and never
       blocks (re-dispatch to retry the attach).
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

## Known limitations

**A small, accepted check-then-act window remains before the tag/Release are
actually created.** `publish`'s recheck of `main`'s tip and of every check
for that commit is the very first thing it does, back-to-back, before
anything else — but GitHub exposes no atomic "create this tag only if branch
`X` is still at commit `Y`" API, so there is no way to make that window
literally zero. In practice it is small (a same-org artifact download plus
the `git tag`/`git push` themselves, on the order of seconds), this is a
manual, maintainer-triggered dispatch rather than a high-frequency automated
path, and the only realistic outcome if the window is ever actually hit is
releasing a commit that genuinely *was* `main`'s verified, all-checks-green
tip moments earlier — not a wrong, unreviewed, or malicious commit, and not
one that skipped this workflow's own fresh test run. See
`docs/planning/adrs/0129-canonical-immutable-release.md`'s "Known
limitations" section for the full reasoning.

If you ever discover a release published a commit that was immediately
superseded by another merge: **do not** retroactively move, delete, or
retag the published release (see Rollback below — tags here are immutable
once published, and this is not the "genuine publishing mistake caught
immediately" case that section's narrow deletion exception covers). Instead,
just cut a new patch (or minor) release from the actual intended tip through
the normal dispatch process above; the superseded release stays as an
accurate record of what `main`'s tip briefly was.

## Rollback

Releases are immutable — never delete or retag a published release to "fix"
it. If a released commit turns out to be broken, release a new patch/minor
version with the fix through the same process above. `gh release delete
vX.Y.Z` (and its tag) is reserved for a genuine publishing mistake caught
immediately after dispatch, before any consumer could plausibly have pinned
it, and should still be treated as an exceptional, logged action, not routine
practice.
