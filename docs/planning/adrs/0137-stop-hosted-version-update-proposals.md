---
id: "0137"
title: "Stop hosted dependency version-update proposals"
status: proposed
proposed_date: "2026-10-09"
deciders:
  - "repository maintainer"
affected_components:
  - ".github/dependabot.yml"
  - "tests/test_repository_security_metadata.py"
  - "docs/commercial_security_attestation.md"
supersedes: "0009"
related:
  - path: "docs/planning/adrs/0009-supply-chain-dependency-cooldown.md"
    relation: proposed-supersession
---

# Stop hosted dependency version-update proposals

## Problem and constraints

The repository's weekly GitHub Actions and pip version-update jobs are hosted
Dependabot work. They create proposals outside the self-hosted quality lane,
while dependency review, `pip-audit`, CodeQL, Trivy, OSV, Scorecard, and
Dependabot vulnerability alerts remain separate security controls. Removing
the version-update configuration must not be represented as removing those
controls or as completed policy before protected integration.

## Considered options

1. Keep ADR-0009's weekly proposals with a seven-day cooldown. This preserves
   automated version discovery but retains the hosted-only work source.
2. Replace Dependabot with a new updater. This adds an unrequested dependency
   and a second update owner.
3. Remove hosted version-update proposals and keep the existing security gates.

## Proposed decision

Select option 3. Delete `.github/dependabot.yml`; remove the obsolete test that
requires it; and update buyer evidence to distinguish vulnerability alerts and
required security workflows from version-update scheduling. This proposal
supersedes ADR-0009 only after ordinary protected-main integration.

## Risks, effects, and follow-up

Dependency freshness can drift because no replacement scheduler is introduced.
Security gates continue to fail closed on vulnerable or unreviewed dependency
changes, but they do not guarantee timely adoption of non-security releases.
The maintainer must approve that operational tradeoff. A later self-hosted
updater requires its own owner contract, immutable inputs, tests, and ADR; it is
not pre-authorized here.

For contributors, no weekly version-update PR is promised. For operators,
Dependabot alerts and the required security workflows remain evidence sources.
Failure of any retained gate remains a merge blocker; absence of a version
proposal is not proof that dependencies are current.
