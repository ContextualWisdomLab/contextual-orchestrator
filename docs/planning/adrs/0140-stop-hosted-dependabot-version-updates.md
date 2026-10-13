---
id: "0140"
title: "Stop repository-hosted Dependabot version updates"
status: proposed
proposed_date: "2026-10-09"
deciders:
  - "repository maintainer"
affected_components:
  - ".github/dependabot.yml"
  - "tests/test_repository_security_metadata.py"
  - "docs/commercial_security_attestation.md"
supersedes: "docs/planning/adrs/0009-supply-chain-dependency-cooldown.md"
superseded-by: null
related:
  - path: "docs/planning/adrs/0004-pr-review-merge-loop.md"
    relation: governance
---

# ADR 0140: Stop repository-hosted Dependabot version updates

## Problem

The repository's Dependabot configuration schedules GitHub-hosted version
update proposals for GitHub Actions and Python dependencies. The maintainer has
explicitly retired that hosted-only update channel. Deleting only the file left
an executable metadata assertion and buyer-facing security documentation that
still required it, making the repository policy internally contradictory and
causing normal tests to fail.

## Constraints

- Do not disable alerts, security updates managed outside this version-update
  file, CodeQL, dependency review, pip-audit, SBOM, Trivy, Scorecard, branch
  protection, or required Checks.
- Do not replace the deleted scheduler with another automation in this slice.
- Preserve review and exact-head Checks as merge conditions.

## Alternatives

1. Retain the accepted seven-day cooldown from ADR 0009. Rejected because it
   continues the explicitly retired hosted version-update channel.
2. Delete the configuration and remove every policy test. Rejected because a
   later file restoration could silently re-enable hosted updates.
3. Delete the configuration and assert that both GitHub-supported filename
   variants remain absent. Selected because it expresses the requested policy
   with one native filesystem contract and no new dependency or workflow.

## Decision

Remove `.github/dependabot.yml` and keep `.github/dependabot.yaml` absent. The
repository metadata suite asserts both names are absent. Security controls that
do not depend on this version-update configuration remain unchanged. ADR 0009
remains historical evidence; this ADR is Proposed until ordinary protected
integration, then supersedes its active cooldown choice.

## Consequences and risks

- A contributor restoring either filename receives a deterministic test
  failure before merge.
- Routine version proposals no longer arrive from repository Dependabot, so
  dependency freshness requires an independently governed process. This PR
  does not claim that successor exists.
- Removing scheduled version updates can delay non-security upgrades. Existing
  vulnerability scans and protected gates detect known vulnerable installed
  versions but do not prove general freshness.

## Operational and failure scenes

- A maintainer opens a dependency PR manually: normal locks, scans, review, and
  protected Checks still apply.
- A contributor restores a Dependabot file: the repository metadata test fails
  and points to this decision.
- A scanner finds a vulnerable pin: the canonical dependency owner repairs the
  lock; the finding is never ignored merely because version scheduling is off.

## Follow-up

After protected merge, mark this ADR Accepted and ADR 0009 Superseded in the
same reviewed decision update. Separately document any replacement dependency
update owner, release contract, cadence, and rollback evidence before relying
on it operationally.
