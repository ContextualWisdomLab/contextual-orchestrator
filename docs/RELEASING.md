# Releasing

This document is for a human maintainer cutting a real, immutable
`contextual-orchestrator` release. It is deliberately narrow — see
[`docs/planning/adrs/0129-canonical-immutable-release.md`](planning/adrs/0129-canonical-immutable-release.md)
for the full design and its explicit non-goals.

## What a release is, and is not

A canonical release is an annotated git tag `vX.Y.Z`, a published GitHub
Release with `immutable: true`, its verified Python wheel and SHA-256 manifest,
and its verified mandatory SBOM. A versioned
URL alone is not evidence that GitHub has locked the tag and assets.

- `.../releases/tag/vX.Y.Z` identifies the version-specific release. Consumers
  must verify its immutable state, exact commit, and asset attestation before
  admitting that version to a released-owner inventory.
- `.../releases/latest` is a **mutable discovery alias**, not a consumer pin.

A release is **not** the same thing as
[`/api/v1/commercial_release_candidates/latest`](commercial_release_candidate.md)
or `contextual_orchestrator/release_authorization.py`. Those evaluate
commercial/buyer readiness inside the running gateway. This release mechanism
only establishes a citable, verified release for an exact protected commit.
It does not establish that every consumer-required API, authentication,
deployment-identity or transport contract is implemented by that release.
LifeOS and other consumers must verify their specific owner contracts too.

The first version remains a candidate until an ordinary protected-main change
selects its SemVer number and records API/schema compatibility in CHANGELOG.md.
The current `0.2.0` project declaration is not release evidence. In particular,
the wheel and signed assets do not prove a deployed gateway's runtime identity
or provide the scoped Actions credential required by #1023. Consumers must
check those contracts separately before replacing a source pin.

## Preconditions

1. The version to release is already merged to `main`: `pyproject.toml`'s
   `[project].version` is the exact `X.Y.Z`, integrated through normal review
   and required checks without exceptions.
2. `CHANGELOG.md` has a non-empty `## [X.Y.Z]` release section. An
   `- Unreleased` or dated suffix is supported.
3. Either `refs/tags/vX.Y.Z` does not exist, or it is an **annotated** tag
   that resolves directly to a commit in protected `main` history. A resume
   uses that tag's exact target, not the current dispatch commit. Lightweight
   tags, unsupported tag objects and unrelated histories fail closed. Never
   replace, promote, move or reuse a tag to make publication succeed.
4. The exact commit has passing required checks. The workflow rechecks
   registered push-triggered jobs and the reported check rollup through
   `scripts/ci/release_checks_gate.sh`, and runs the full test suite fresh.
   Each named release-critical push check must conclude `success`;
   additional checks may conclude `success`, `skipped`, or `neutral`.
   Protected integration still requires all applicable organization gates
   and reviews.
   A newly merged commit whose expected push checks have not yet registered
   is not ready. Re-dispatch after the genuine required evidence exists;
   do not weaken the expected check inventory.
5. A successful `security.yml` run for that exact commit exposes a non-empty
   `cyclonedx-sbom/cyclonedx-sbom.json` artifact. Lookup, download, upload,
   empty-file or content-verification failure is fatal, not best effort.
   The read-only release job builds the Python wheel from that same checkout,
   installs it into an isolated directory to verify its declared version and
   package contents, compares two builds at the source commit's fixed timestamp,
   records its SHA-256 digest, and passes both files to publication.
   The build and isolated install use `uv` with Python 3.12 so they do not rely
   on runner-global `setuptools` or `pip`. This wheel
   is the installable Python package; the separately built Rust decision
   measurement wheel remains a distinct dependency and is not bundled here.
6. A repository administrator has enabled GitHub release immutability before
   publication. The normal workflow token has no Administration permission;
   do not add an administrative secret or expand the publisher's authority
   merely to read or change this setting. The publisher validates the actual
   public `immutable: true` result and release/asset attestations before
   reporting success. A setting that was disabled or changed during publication
   can leave a complete but mutable public release; that is a **failed** run
   and is ineligible for consumption, not an automatic deletion/retagging case.
7. The runner's GitHub CLI supports `gh release verify` and
   `gh release verify-asset`. Missing verification capability fails closed;
   do not replace it with a filename or hash-only success claim.

## Cutting a release

1. Use **Actions → Release → Run workflow**, or
   `gh workflow run release.yml -f version=X.Y.Z`.
2. Select branch `main`; other refs cannot publish.
3. Enter `X.Y.Z` without a leading `v`, matching `[project].version` exactly.
4. The read-only `verify` job:
   - classifies the exact `refs/tags/vX.Y.Z`, rejecting lightweight tags;
   - peels an annotated tag to its commit and verifies protected-main ancestry;
   - treats only confirmed 404 / release-not-found lookups as absence, not
     rate-limit, authentication, network or server errors;
   - checks out `TARGET_SHA`; a fresh publication must match the current
     protected-main tip, while a resume may use its verified ancestor;
   - checks the exact-head rollup and project version;
   - installs locked test dependencies, builds the Rust decision measurement
     with `maturin develop`, then runs `uv run --no-sync python -m pytest -q`;
   - renders notes from the exact commit's CHANGELOG section, cutting a
     section over GitHub's 125,000-character body limit on a line boundary
     and linking the complete CHANGELOG.md at that commit;
   - downloads the exact-commit mandatory CycloneDX SBOM, builds the Python
     wheel, records its SHA-256 digest, and passes these with the notes to the
     publisher through an Actions artifact.
5. The write-scoped `publish` job, only after verification succeeds:
   - rechecks fresh-main identity and exact-target checks before mutation;
   - requires non-empty notes, SBOM and wheel inputs, then checks the wheel
     against the SHA-256 manifest;
   - creates and pushes an annotated tag only for a fresh publication;
   - verifies the exact remote tag object and its peeled target, so GitHub
     cannot synthesize a tag from a default branch;
   - admits an existing release only as a typed, matching-tag, non-prerelease
     Draft, or a complete already-published immutable release;
   - creates a new release with `--verify-tag --draft`;
   - attaches any missing SBOM, wheel and manifest **only while the release is
     a Draft**, then downloads each and compares its bytes with the verified
     input;
   - publishes the verified Draft. An already-public immutable release is
     verify-only and is neither recreated, edited nor uploaded to;
   - requires the resulting release to be non-Draft, non-prerelease,
     matching-tag and `immutable: true`, then runs `gh release verify` and
     `gh release verify-asset` for each asset.
6. Confirm the version-specific release, successful publication run, exact
   tag/commit, immutable state, wheel digest, SBOM and signed asset attestations. Do not admit
   a release merely because it appears in the GitHub Releases list.

## PyPI publication

After `publish` succeeds, the `publish-pypi` job in the same run uploads the
verified wheel to PyPI as `contextual-orchestrator`. It never rebuilds and
installs nothing. `verify` has already run `twine check --strict` on the exact
wheel, holding its digest in memory across the check. twine and its
dependencies come from the hash-locked `requirements-release-twine.txt`
(regenerate with the command in its header), and that step gets no GitHub
token. `publish-pypi` downloads
the `release-publish-inputs` artifact, re-checks `SHA256SUMS`, and requires
that manifest to equal the one attached to the immutable GitHub Release. It
then runs a stdlib-only PyPI pre-check, uploads with
`pypa/gh-action-pypi-publish` pinned to a full commit SHA, and finally
requires PyPI's file list for the version to equal the manifest. Only the
wheel is uploaded; no sdist is built or published.

### Pre-merge checklist (repository and PyPI owners)

`environment: pypi` is only a real gate once the environment exists and is
protected, and the organization `PIPY_TOKEN` secret is visible to every
repository on its access list. Before merging the PyPI job:

Items 1 to 3 are enforced. Early in the read-only `verify` job, before any
tag or GitHub Release exists, the step "Require a protected pypi environment
before any tag or release exists" reads
`GET /repos/{owner}/{repo}/environments/pypi` with the job's read-only token.
It fails the run unless the environment exists, has a `required_reviewers`
protection rule with at least one reviewer, and has a non-null
`deployment_branch_policy`. Any other lookup error also fails the run. For
`GITHUB_TOKEN`, that endpoint needs only `actions: read`, which `verify`
already has. Until the environment is set up, every release stops there,
before anything is published.

1. Create the `pypi` GitHub environment in contextual-orchestrator.
2. Restrict its deployment branches to `main`.
3. Add required reviewers, so each PyPI upload needs a human approval.
4. Credentials, preferred first:
   - **Trusted Publishing (preferred).** Register a PyPI Trusted Publisher
     with owner `ContextualWisdomLab`, repository `contextual-orchestrator`,
     workflow `release.yml` and environment `pypi`. For the first upload of a
     new project this is a PyPI "pending publisher". Then leave the token
     unavailable to this repository.
   - **API token.** Do **both** of the following:
     - Store the token as a `pypi` *environment* secret named `PIPY_TOKEN`.
       Only jobs that deploy to `pypi` can read it, which means after a
       required reviewer approves and only from `main`.
     - **And** restrict the organization `PIPY_TOKEN` secret's repository
       access list. Remove contextual-orchestrator, or at least every
       repository that does not publish with it. An environment secret only
       *overrides* the same-named organization secret inside the `pypi` job.
       Every other job and workflow in the repository still resolves
       `secrets.PIPY_TOKEN` to the organization secret, with no reviewer and
       from any branch, unless the organization secret's access is
       restricted.

     The workflow references the secret in exactly one place, the upload
     step's `password:` input.

If the first publication reports an empty password or a Trusted Publishing
exchange failure, neither credential is available to this repository.

The project `contextual-orchestrator` does not exist on PyPI yet. A
project-scoped API token cannot be created before the project exists, so the
very first upload needs either a pending Trusted Publisher or an
account-scoped token. Replace an account-scoped token with a project-scoped
one right after the first upload.

### Re-running and known limitations

Re-running is safe. `skip-existing: true` makes an already-uploaded, identical
wheel a no-op. A PyPI version that already holds any file whose name or
SHA-256 is not in the verified manifest fails the job before upload. PyPI
never allows a file to be replaced or a version to be reused, so such a
mismatch needs a new version, never a retry.

- The `release-publish-inputs` artifact is kept for one day
  (`retention-days: 1`), so "re-run failed jobs" for `publish-pypi` only works
  within that day. After that, re-dispatch the same version. The run
  rebuilds the wheel, `publish` verifies it byte-for-byte against the
  immutable release asset, and `publish-pypi` then retries the upload.
- That byte-for-byte comparison relies on the wheel build being reproducible.
  `pyproject.toml` declares no `[build-system]`, so `uv build` uses the
  default setuptools backend at whatever version is current. A setuptools
  release between the original run and a re-dispatch can change the wheel
  bytes and make the resume fail closed. Pinning `[build-system]` would
  remove that risk.

## Recovery and known limitations

An interrupted Draft is recoverable without deleting it or moving its tag.
The same version can resume missing-asset upload or final publication after
all current gates pass. Existing assets are compared byte-for-byte and are
never clobbered. A public release missing its mandatory asset, a mutable
public release, mismatching tag, prerelease, untyped lifecycle field or
unavailable metadata is rejected before resume-side mutation.

A completed immutable release can be checked again without mutation. An
attestation failure, including a temporarily unavailable attestation, is
non-passing evidence; a later verification retry does not require deleting
or republishing that release.

The final main-tip check and tag creation are not an atomic compare-and-set.
A concurrent merge can land in that interval. The publisher checks exact tag
identity, but a verified fresh tip might no longer be the newest tip by the
time publication completes. Correct the version through another normal
release; never move the previous tag. For an annotated-tag resume, all gates
bind to that tag's target rather than the newer main tip.

Draft assets remain mutable until publication, so another authorized publisher
can race the draft content comparison. The post-publication signed asset
verification detects a mismatch and fails the run; it does not roll back
publication or authorize a mismatching asset for consumers. Repository-wide
publisher serialization and maintainer access control remain necessary.

Release immutability must be enabled by the repository owner. This workflow
neither changes that administrative setting nor treats a successfully created
but mutable public release as safe. Enabling the setting afterward does not
retroactively validate a failed release. Investigate it and use a new reviewed
version rather than automatically deleting or recycling its tag.

## After a release

Bump `[project].version` and open the next non-empty CHANGELOG section in an
ordinary PR. Consumers with owner handoffs, including `keyverse#132`,
`bandscope#881`, `contextual-orchestrator#971` and LifeOS's `#1023` dependency,
can propose a version bump only after their required released API and runtime
contracts have been verified. A tag-only, source-checkout or unreleased branch
substitution is not a consumer repair.

## Rollback

Do not delete, retag or overwrite a published release to repair a defect.
Publish a new patch/minor version through the same reviewed process. Deleting
an immutable release is not a way to reuse its tag name. Incomplete Drafts
are resumed rather than deleted by this workflow.

## Normative references

- [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- [GitHub CLI release creation](https://cli.github.com/manual/gh_release_create)
- [Release attestation verification](https://cli.github.com/manual/gh_release_verify)
- [Release asset verification](https://cli.github.com/manual/gh_release_verify-asset)

The executable local regression is
`python -m pytest -q tests/test_release_immutable_publication.py`. It executes
the publisher's real shell against a stateful CLI boundary with no network or
publication authority. This is scoped regression evidence, not a substitute
for hosted exact-head checks, independent review, or real release verification.
