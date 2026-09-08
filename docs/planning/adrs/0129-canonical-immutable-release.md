---
id: "0129"
title: "Publish a canonical immutable GitHub Release, gated on protected-main evidence"
status: proposed
proposed_date: "2026-09-02"
deciders:
  - "repository maintainer"
affected_components:
  - ".github/workflows/release.yml"
  - "scripts/ci/release_notes.py"
  - "scripts/ci/release_checks_gate.sh"
  - "docs/RELEASING.md"
related:
  - path: "docs/planning/adrs/0020-fail-closed-release-authorization.md"
    relation: "distinct-concern-shares-fail-closed-spirit"
success_criteria:
  - metric: "consumer pin target"
    target: "a completed GitHub Release exists at an immutable vX.Y.Z tag and includes its mandatory CycloneDX SBOM"
    source: "release.yml exact-tag and asset verification"
  - metric: "no vendored source SHA required"
    target: "consumers can pin a released API/client/schema contract instead of a mutable sibling head or copied source"
    source: "owner acceptance criteria, contextual-orchestrator#971"
  - metric: "release identity ambiguity"
    target: "a branch named vX.Y.Z cannot satisfy release-tag existence or identity checks"
    source: "tests/test_release_supply_chain_contract.py"
---

# Publish a canonical immutable GitHub Release, gated on protected-main evidence

## Status

**Proposed.** The workflow implementation exists on PR #1030, but this ADR is intentionally not Accepted yet. The Python-runtime prerequisite #995 must land first, #1030 must be non-force-restacked onto that protected-main descendant, its final exact head must obtain authoritative hosted GREEN evidence, and a real release has not yet been cut. Provenance/attestation and reproducibility evidence beyond the mandatory CycloneDX SBOM also remain release-readiness gaps rather than claims of completion.

## Problem

`contextual-orchestrator` is a canonical owner for LLM gateway/API/client/schema behavior. Consumers such as Keyverse, BandScope, and Wardnet must consume a versioned owner contract; copying source or pinning a mutable sibling head breaks the CWL ownership boundary and prevents an owner-issued compatibility promise.

The repository already has PR-scoped commercial-release authorization (`contextual_orchestrator/release_authorization.py` and ADR 0020), but that concern answers whether a pull request satisfies buyer-facing governance evidence. It does not create or identify an immutable publication artifact. Reusing it as a tag publisher would conflate two bounded responsibilities and duplicate GitHub branch/ruleset bookkeeping.

The release mechanism therefore owns only publication identity and publication evidence for an exact commit. Protected-branch governance remains where it already belongs; consumers receive only the resulting released contract.

## Constraints

1. No automatic release on every merge. Publication is a deliberate `workflow_dispatch` operation on `main`.
2. A fresh publication must operate on the protected `main` tip that was actually verified. If `main` advances before mutation, publication fails closed.
3. An existing release tag is immutable. It is never moved, rewritten, or reused for another commit.
4. A previously pushed tag may be resumed only when its target is an ancestor of current `main`. Every resume gate evaluates the tag's own target commit, not a newer dispatch SHA.
5. Tag absence is established only by a confirmed exact-tag 404. Authentication, rate-limit, network, or server failures are not interpreted as absence.
6. A canonical release is incomplete without its required exact-commit CycloneDX SBOM. SBOM lookup, download, handoff, upload, and post-upload verification are fail-closed.
7. The release workflow does not weaken or substitute repository/org checks, self-approve, or synthesize GREEN from a predecessor head.
8. No consumer may depend on this PR branch. Consumers switch only after an actual immutable release exists.

## Decision

### Exact release identity

The workflow resolves release existence in GitHub's Git-reference namespace:

`GET /repos/{owner}/{repo}/git/ref/tags/vX.Y.Z`

GitHub's reference API requires callers to distinguish `heads/<branch>` from `tags/<tag>` and returns 404 when that exact reference does not exist. This is materially different from resolving an arbitrary commit-ish. A branch named `vX.Y.Z` therefore cannot impersonate the release tag.

The returned Git object is handled explicitly:

- `object.type == commit`: lightweight tag; that commit is the tag target.
- `object.type == tag`: annotated tag; peel the tag object once through `/git/tags/{sha}` and require its target type to be `commit`.
- any other or ambiguous type: fail closed.

This repository creates annotated tags for fresh publications. The workflow nevertheless reads lightweight tags defensively because a pre-existing ref can exist independently of this workflow and must be classified before any decision is made.

Immediately before GitHub Release creation, the publish job independently verifies that remote `refs/tags/vX.Y.Z` exists, that its Git object SHA matches the fetched/created local tag object, and that the local tag peels to `TARGET_SHA`. `gh release create` is never allowed to become the mechanism that implicitly creates an unverified tag from a default branch or other commit-ish.

### Fresh publish versus resume

No existing exact tag means a fresh publication. `TARGET_SHA` is the dispatch SHA and must equal protected `main`'s current tip before verification and again immediately before mutation.

An existing exact tag means resume only when its target is identical to or an ancestor of current `main`. `TARGET_SHA` becomes the tag target. Main is allowed to have advanced after the earlier tag push because the tag is already immutable; version validation, checks, tests, release-note rendering, and SBOM lookup all operate on `TARGET_SHA`.

A tag that is not on current `main` history is a conflict, not a recovery case. The workflow fails and requires a new version rather than moving the tag.

### Verification gate

For `TARGET_SHA`, the read-only verify job:

1. requires all repository-owned expected push checks to be registered;
2. requires every reported check to have an acceptable terminal conclusion;
3. parses the project's declared version and requires exact equality with the dispatch input;
4. runs the full locked test suite fresh on that exact commit;
5. renders non-empty release notes from the matching CHANGELOG section;
6. finds a successful exact-commit `security.yml` run and downloads its `cyclonedx-sbom` artifact;
7. requires a non-empty `cyclonedx-sbom.json` and hands both notes and SBOM to the write-scoped publish job with `if-no-files-found: error`.

The write-scoped publish job repeats the checks gate immediately before mutation, verifies the downloaded inputs, creates the annotated tag only for a fresh publication, verifies exact remote tag identity, creates or resumes the GitHub Release, and verifies the mandatory SBOM is attached. If Release creation succeeds but SBOM attachment fails, the workflow fails; a later dispatch resumes the same immutable tag/Release until the mandatory asset is present. That transient partial state is not reported as a successful canonical release.

### Least privilege

Repository-controlled tests and release-note rendering run in the read-only `verify` job with no persisted git credential. `contents: write` exists only in `publish`, after the read-only gate has succeeded. `checks: read` is used for exact-commit status verification; the workflow does not reproduce org-central review/security ownership.

## TDD evidence

The current repair lineage on #1030 includes:

- `9b93a215530c96509de9d368f0008b713fe0640b`: RED contract rejecting generic `commits/v${RELEASE_VERSION}` tag lookup and optional SBOM behavior.
- `788dfce254604f1d8cec1681205faf19d6125333`: production GREEN using exact `git/ref/tags/...` identity and fail-closed SBOM evidence/attachment.
- `29ee4ce28d68c7dc825a998434dd944aff2352f5`: contract assertions aligned to the repaired workflow step names.
- `d22586f8e8dd9be3762ed7bf02762c9f82fbf771`: release runbook brought code-current with the same invariants.

Hosted GREEN is not claimed from these commits. On the previously observed `d22586f8...` head, CodeQL PR run `33688739873` ended in `startup_failure` and other required workflows were non-terminal. The central runner/control-plane owner path is tracked in `ContextualWisdomLab/.github#712`.

## Alternatives considered

### Use the generic commits endpoint for `vX.Y.Z`

Rejected. A commit-ish resolver is not an exact tag-namespace assertion. The release identity must distinguish `refs/tags/...` from `refs/heads/...` before publication.

### Let `gh release create` create a missing tag implicitly

Rejected. GitHub release creation accepts a `target_commitish` when the tag does not already exist; relying on that behavior expands the mutation surface and weakens the workflow's exact-tag proof. The tag must exist and be verified before the Release is created.

### Make the SBOM best-effort

Rejected. The repository already produces CycloneDX evidence on the security path, and the commercial fleet contract requires release evidence to be attributable to the exact protected commit. Publishing successfully while that mandatory evidence is absent would create a consumer-visible artifact whose supply-chain evidence is weaker than the release contract.

### Re-run every org-central security/review workflow inside release.yml

Rejected. Those checks have canonical owners and are already represented in protected-main/check evidence. Duplicating them here would create mutable local forks of governance. The release workflow consumes their exact-commit results and re-runs only repository-owned release-specific verification.

### Reuse PR-scoped `release_authorization.py` as the publisher

Rejected. It is a buyer/readiness evidence evaluator keyed to a PR, not a Git publication aggregate. Publication remains a separate bounded context with a minimal dependency on GitHub's protected-commit evidence.

## Consequences

Positive effects:

- consumers gain a future immutable owner-issued pin instead of source copying;
- branch/tag namespace confusion is removed from release identity;
- interrupted tag/Release publication can be resumed without retagging;
- missing exact-commit SBOM evidence blocks successful publication;
- write credentials are kept away from repository-controlled test execution.

Costs and residual risks:

- GitHub does not expose an atomic "create tag only if branch still equals SHA" operation, so a small fresh-publish check-then-act window remains after the final `main`-tip check. The mitigation is fail-closed prechecks plus exact remote tag verification; if a concurrent merge wins that window, publish a new patch/minor version and never move the earlier tag.
- GitHub Release creation and asset upload are separate mutations. A Release can therefore exist temporarily without the SBOM after an interrupted run; workflow success is withheld until the asset is verified.
- The current path establishes SBOM evidence but does not yet establish the broader provenance/attestation and reproducibility evidence required by the fleet's final release-ready definition. Those are follow-up acceptance items; this ADR remains Proposed until they are resolved or explicitly superseded by another owner decision.
- #1030 currently depends on #995's supported-runtime correction and on recovery of hosted runner/control-plane execution. Neither is bypassed here.

## Rollback and recovery

Published release tags are immutable. Functional rollback is a forward fix in a new patch/minor release. Routine delete/retag is not a recovery mechanism.

For an interrupted publication on a valid existing tag, re-dispatch the same version. The workflow re-verifies that tag target and completes any missing Release/SBOM mutation without moving the tag.

A tag pointing outside current `main` history, an ambiguous tag object, an unconfirmed lookup failure, a failed exact-commit check, or missing SBOM evidence is a stop condition requiring repair before publication.

## Acceptance before status may become Accepted

- #995 merged normally and #1030 non-force-restacked to the resulting protected-main descendant.
- all final exact-head required repository and org-central checks terminal GREEN with no valid unresolved review findings.
- release docs and product/technical gap baseline agree with the final implementation.
- first canonical version published at an exact tag with verified mandatory SBOM.
- release provenance/attestation and reproducibility requirements either implemented and tested or governed by a separate Accepted owner ADR with an explicit contract.
- consumer bump validated against the released API/client/schema rather than this PR branch or an arbitrary source SHA.

## Traceability and primary references

GitHub. (2026). *REST API endpoints for Git references*. GitHub Docs. https://docs.github.com/en/rest/git/refs

GitHub. (2026). *REST API endpoints for Git database*. GitHub Docs. https://docs.github.com/en/rest/git

GitHub. (2026). *REST API endpoints for releases*. GitHub Docs. https://docs.github.com/en/rest/releases/releases

Primary-document check performed 2026-09-03. GitHub's reference documentation explicitly requires the requested ref to be namespaced as `heads/<branch>` or `tags/<tag>` and reports 404 for a missing exact ref; its releases documentation states that `target_commitish` is used to determine where a tag is created when the tag does not already exist. These semantics are the reason this ADR requires exact tag-ref proof before Release creation.