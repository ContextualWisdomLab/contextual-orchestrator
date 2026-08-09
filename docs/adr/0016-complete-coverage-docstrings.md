# ADR-0016: Complete production coverage and public docstrings

## Status

`accepted_architecture`

## Context and decision drivers

Coverage evidence can appear complete while omitting owned modules, branches,
functions, package-import paths, or public API explanation. Percentage chasing
can also hide real 4xx/5xx and state-transition defects exposed by realistic
tests. Commercial and acquisition evidence needs exact source identity and
beginner-readable contracts, not a threshold detached from behavior.

## Considered alternatives

- accept a lower repository-wide percentage: leaves unclassified product risk;
- exclude difficult or optional production files: can hide real behavior;
- add no-op line execution: raises a number without proving a contract;
- require complete owned statement, branch, function, line, package, and public
  docstring evidence with realistic tests: selected.

## Decision

Release acceptance requires exact 100% owned production statement and branch
coverage, and 100% function/line coverage where the selected tooling reports
them. Every public class, method, and function has a beginner-readable
docstring. The owned-source manifest and checked-out revision are evidence, so a
synthetic merge, predecessor head, stale source tree, skipped-required check, or
status alone is not contributor-head success.

Tests exercise observable contracts. When a coverage test exposes a real
HTTP/state/provider defect, the defect receives RCA and a failing regression
before the smallest production repair. Structurally unreachable code is removed
or its invariant is documented; it is not excluded to preserve a percentage.

## Consequences

Every production branch carries a verification and documentation cost. Reports
are more defensible, but complete coverage remains necessary rather than
sufficient: security scans, fuzz, packaging, provenance, independent review,
and protected-main acceptance remain separate gates.

## Failure and recovery

Any missed statement/branch/public docstring, source-tree mismatch, package
build/install/import failure, or required optional-path gap blocks coverage
acceptance. RCA distinguishes a bad assumption, test gap, product defect,
unreachable guard, and infrastructure failure. Recovery adds the real contract
test/docstring or reverts the behavior; it never lowers thresholds or adds a
blanket exclusion.

## Security, privacy, and governance impact

Security boundaries receive adversarial, property, and fuzz evidence in
addition to deterministic paths. Fixtures contain no live secrets and coverage
artifacts do not include provider credentials or private reasoning. Coverage
does not impersonate independent approval.

## Compatibility and migration

Tools may change, but the owned-source set, exact revision, branch semantics,
function/line evidence, package smoke, and public API contract remain explicit.
Optional adapters require executable evidence or a clearly non-release status.

## Verification and acceptance

Run focused regressions, the full functional/integration suite, branch-enabled
coverage over the owned production manifest, public-docstring inspection,
package build/install/import isolation, property/Atheris seams, security gates,
and documentation fitness. Classify every workflow by the commit actually
checked out.

## Rollback and supersession

Rollback reverts the production change or supplies the missing real test and
docstring. No rollback weakens the threshold or hides behavior. A stronger
evidence system may supersede this ADR only if it preserves exact source
identity and complete statement, branch, function, line, package, and public
contract proof.

## References

NIST SP 800-218 and NIST SP 800-218A. See
[the reference index](../REFERENCES.md).
