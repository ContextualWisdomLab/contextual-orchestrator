# ADR-0011: Release coverage and provenance

## Status

`accepted_architecture`

## Context and decision drivers

A unit-test pass does not prove branch behavior, public documentation, package
installability, dependency integrity, artifact identity, migration recovery, or
independent acceptance. Release claims must bind these views to one unchanged
protected revision.

## Considered alternatives

- release from any green feature branch: fast but bypasses integrated authority;
- accept line coverage alone: misses branch behavior and excluded production;
- trust a built artifact without source/provenance linkage: irreproducible;
- require one protected revision with complete functional, security, package,
  provenance, review, and recovery evidence: selected.

## Decision

Owned production code reaches 100% statement and branch coverage and the
repository's public-docstring target without excluding executable behavior to
improve a metric. A release candidate also passes realistic integration, fuzz,
security, compatibility, build/install/import, SBOM, provenance,
reproducibility, migration/rollback, and independent-review gates. Version,
changelog, source revision, artifacts, and published identity agree.

## Consequences

Release preparation is stricter than ordinary development and may reveal real
defects late in a feature branch. Coverage gaps produce tests or fixes, not
weakened thresholds.

## Failure and recovery

Any changed head, missing/failed gate, artifact mismatch, unresolved finding, or
rollback failure blocks publication. Repair creates a new candidate and repeats
all head-bound evidence. A bad release is stopped, identified exactly, rolled
back compatibly, and reconciled.

## Security, privacy, and governance impact

SBOM and provenance reduce supply-chain ambiguity. Logs and artifacts still
exclude secrets and unnecessary PII. Repository evidence does not manufacture
external certification, penetration testing, SLO, or buyer signature.

## Compatibility and migration

Existing development tests remain fast feedback. Release workflows add gates at
protected-main and artifact boundaries without requiring live credentials in
offline tests.

## Verification and acceptance

The release manifest binds commit, tag, version, changelog, package hashes,
SBOM, provenance, coverage, docstrings, test/security/fuzz results, reviewer
state, migration evidence, and reproducible install/smoke output.

## Rollback and supersession

Rollback restores a known compatible artifact and schema while preserving the
failed identity for incident analysis. Supersession requires equal or stronger
source-to-artifact and independent-control guarantees.

## References

NIST SP 800-218 and NIST SP 800-218A. See
[the reference index](../REFERENCES.md).
