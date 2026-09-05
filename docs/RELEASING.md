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
3. Either no exact tag ref `refs/tags/vX.Y.Z` exists yet, or one does and
   resolves to a commit that is an ancestor of `main`'s current tip (the
   commit you're dispatching, or an earlier one `main` has since advanced
   past) — in which case the workflow safely resumes using **the tag's own
   target commit**, never a same-named branch and never the commit you happen
   to be dispatching against. If that tag has no GitHub Release published
   yet, the workflow creates one; if the Release already exists after a
   previously interrupted publication, the workflow verifies or restores
   the mandatory release assets without moving the tag. A tag that resolves
   to a commit that is **not** an ancestor of `main`'s current tip is rejected
   outright: bump the version rather than reusing or moving an immutable tag.
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
     check-run entries yet. This is expected and safe: wait for those
     workflows to actually start, then re-dispatch. It is distinct from a
     genuine pending/failed check, which the same gate reports as "not both
     complete and green" instead.
5. The exact commit has a successful `security.yml` run exposing the
   `cyclonedx-sbom` artifact and a non-empty `cyclonedx-sbom.json`. The
   canonical release path treats this SBOM as required supply-chain evidence,
   not optional decoration; lookup, download, empty-file, upload, or
   post-upload verification failure fails the run closed.

## Cutting a release

1. Go to **Actions → Release → Run workflow** in the GitHub UI (or
   `gh workflow run release.yml -f version=X.Y.Z`).
2. Select branch `main` (the workflow refuses to run against anything else).
3. Enter the exact version, e.g. `0.2.0` — no leading `v`, must match
   `pyproject.toml` byte-for-byte.
4. Dispatch. The workflow is two jobs, least-privilege: `verify` runs with no
   write permission and no persisted git credential while it executes any
   repository-controlled code; `publish` holds the write token and does
   nothing but verify final publication inputs, tag, and publish. In order:
   - **`verify`** (read-only):
     - queries `repos/$REPO/git/ref/tags/vX.Y.Z`, not the generic commits
       endpoint, so a same-named branch cannot impersonate a release tag.
       A lightweight tag resolves directly to its commit; an annotated tag
       is peeled through the tag-object API and must resolve to a commit;
     - decides `TARGET_SHA`, the exact commit every later gate evaluates
       against. No tag yet: `TARGET_SHA` is the dispatched commit itself (a
       fresh publish). A tag that exists and is an ancestor of `main`'s
       current tip: `TARGET_SHA` is the *tag's own target commit* (a resume),
       regardless of how far `main` has advanced. A tag that is not an
       ancestor of `main` fails closed. A failed tag or Release lookup is
       treated as "absent" only on a *confirmed* 404 / "release not found";
       rate-limit, auth, network, or 5xx errors fail closed instead of being
       guessed away;
     - checks out `TARGET_SHA` so every subsequent step reads *that* commit's
       tree, never a possibly-newer `main` tip;
     - for a **fresh publish only**, fails closed if `TARGET_SHA` is not
       `main`'s current tip. A resume skips this comparison because `main`
       having advanced past the tag is precisely the recoverable case;
     - fails closed (via `scripts/ci/release_checks_gate.sh`) unless all
       repository-owned expected push checks have registered for
       `TARGET_SHA` and every check GitHub reports for it is terminal-green,
       skipped, or neutral;
     - fails closed if the input version does not match `TARGET_SHA`'s
       `pyproject.toml` `[project]` table;
     - runs the full test suite fresh on `TARGET_SHA` (`uv run --locked
       --extra api --extra db --extra queue --group dev python -m pytest -q`);
     - renders release notes from `TARGET_SHA`'s `CHANGELOG.md` matching
       section (`scripts/ci/release_notes.py`);
     - requires a successful exact-commit `security.yml` run, downloads its
       `cyclonedx-sbom` artifact, and rejects a missing or empty
       `sbom-download/cyclonedx-sbom.json`;
     - uploads both the rendered notes and SBOM for `publish`; a missing file
       is an error, not an ignored artifact condition.
   - **`publish`** (write-scoped, only after `verify` succeeds):
     - for a **fresh publish only**, re-verifies `main`'s tip has not advanced
       while `verify` was testing; for both fresh and resumed publication,
       re-verifies every check for `TARGET_SHA` immediately before mutation;
     - verifies the downloaded release notes and SBOM are non-empty;
     - creates and pushes annotated tag `vX.Y.Z` only when it does not already
       exist;
     - verifies `refs/tags/vX.Y.Z` really exists on `origin`, its remote Git
       object matches the fetched local tag object, and the tag peels to
       `TARGET_SHA`. GitHub Release creation never gets a chance to synthesize
       an implicit tag from a branch/default branch;
     - creates the GitHub Release using the verified notes unless resuming an
       already-created Release;
     - verifies `cyclonedx-sbom.json` is attached. If it is missing, uploads
       it and then re-reads the Release assets. Upload or verification failure
       fails the workflow closed; re-dispatch resumes without moving the tag.
5. Confirm both the versioned Release and its `cyclonedx-sbom.json` asset at
   `.../releases/tag/vX.Y.Z`. Use `/releases/latest` only to discover the
   newest version, never as an immutable consumer pin.

## After a release

- Bump `pyproject.toml`'s `version` and open a new `## [next-version] -
  Unreleased` `CHANGELOG.md` section in an ordinary PR, so the repository is
  never left claiming to already be the version it just released.
- Downstream consumers with an open handoff on this gap
  (`ContextualWisdomLab/keyverse#132`, `ContextualWisdomLab/bandscope#881`,
  the Wardnet consumer-owner handoff on `contextual-orchestrator#971`) can
  bump to the published tag instead of a vendored source SHA.

## Known limitations

**This section describes a fresh publish only.** A resume of a tag-only
interrupted publication evaluates every gate against the tag's own target
commit, which is already immutable once pushed — there is no live
`main`-tip comparison to race for a resume, so the window below does not
apply to it.

**A small, accepted check-then-act window remains before the tag/Release are
actually created.** `publish`'s recheck of `main`'s tip and of every check
for that commit runs before publication, but GitHub exposes no atomic
"create this tag only if branch X is still at commit Y" API. The workflow
therefore minimizes the window, rejects a stale fresh publish, and verifies
the exact remote tag identity before creating the GitHub Release. If a
concurrent merge lands after the final tip check but before the tag push, the
released commit can have been `main`'s verified tip moments earlier rather
than the newest tip. Cut a new patch/minor release from the intended current
tip; never move or overwrite the earlier immutable tag.

A Release object can also exist temporarily without its required SBOM when
`gh release create` succeeds and a later asset upload fails. That state is
**not** a successful canonical release run: the workflow fails closed and a
re-dispatch resumes at the same immutable tag/Release until the mandatory
asset is present and verified. Consumers should use a version as release-ready
only after the release workflow itself has completed successfully.

## Rollback

Releases are immutable — never delete or retag a published release to "fix"
it. If a released commit turns out to be broken, release a new patch/minor
version with the fix through the same process above. `gh release delete
vX.Y.Z` (and its tag) is reserved for a genuine publishing mistake caught
immediately after dispatch, before any consumer could plausibly have pinned
it, and should still be treated as an exceptional, logged action, not routine
practice.
