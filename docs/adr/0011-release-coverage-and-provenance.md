# ADR-0011: Release coverage and provenance

## Status

`accepted_architecture`

Protected `main` runs Tests, Fuzz, and the required Security workflow
(CodeQL, dependency review, pip-audit, CycloneDX SBOM, Trivy). Those job
results are merge gates. They are not an external certification.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

A unit-test pass does not prove branch behavior, public documentation,
package installability, dependency integrity, artifact identity, migration
recovery, or independent acceptance (National Institute of Standards and
Technology, 2022, 2024b). Release claims must bind these views to one
unchanged protected revision.

A failing Trivy or pip-audit job is a real finding, not a flake. Remediate
by bumping the pinned dependency and regenerating `requirements.lock`. Do
not weaken, `continue-on-error`, or disable the gate.

## Considered alternatives

- Release from any green feature branch: fast but bypasses integrated
  authority.
- Accept line coverage alone: misses branch behavior and excluded
  production.
- Trust a built artifact without source/provenance linkage: irreproducible.
- Require one protected revision with functional, security, package,
  provenance, review, and recovery evidence: selected.

## Decision

Owned production code aims for complete statement and branch coverage and
the repository public-docstring target (`fail-under = 80` in
`pyproject.toml` for the OpenCode review extra) without excluding executable
behavior to improve a metric. A release candidate also passes realistic
integration, fuzz, security, compatibility, build/install/import, SBOM,
provenance, reproducibility, and independent-review gates.

The org `code_scanning` ruleset is CodeQL-only so multiple code-scanning
tools do not fight over one PR ref. Gating happens via Security **job
results**.

## Consequences

Release preparation is stricter than ordinary development. Coverage gaps
produce tests or fixes, not weakened thresholds. Commercial readiness
endpoints remain process-local evidence, not a published identity.

## Failure and recovery

Any changed head, missing or failed gate, artifact mismatch, unresolved
finding, or rollback failure blocks publication. Repair creates a new
candidate and repeats all head-bound evidence.

## Security, privacy, and governance impact

SBOM and provenance reduce supply-chain ambiguity. Logs and artifacts still
exclude secrets and unnecessary PII. Repository evidence does not
manufacture external certification, penetration testing, SLO, or buyer
signature.

## Compatibility and migration

Existing development tests remain fast feedback. Release workflows add gates
at protected-main and artifact boundaries without requiring live credentials
in offline tests. The lockfile is hash-pinned; never hand-edit hashes.

## Verification and acceptance

The release identity binds commit, version, package hashes, SBOM,
provenance, coverage, test/security/fuzz results, and reviewer state.

## Rollback and supersession

Rollback restores a known compatible artifact and schema while preserving
the failed identity for incident analysis. Supersession requires equal or
stronger source-to-artifact and independent-control guarantees.

## References

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

National Institute of Standards and Technology. (2024b). *Secure software
development practices for generative AI and dual-use foundation models: An
SSDF community profile* (NIST SP 800-218A).
https://doi.org/10.6028/NIST.SP.800-218A

See also [docs/REFERENCES.md](../REFERENCES.md).
