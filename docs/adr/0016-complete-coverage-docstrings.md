# ADR-0016: Complete production coverage and public docstrings

## Status

`accepted_architecture`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Coverage evidence can appear complete while omitting owned modules, branches,
functions, package-import paths, or public API explanation. Percentage
chasing can also hide real 4xx/5xx and state-transition defects (National
Institute of Standards and Technology, 2022, 2024b).

This lab’s current runtime is stdlib Python. Hypothesis property tests and
optional Atheris fuzzing cover untrusted-input parsers. The OpenCode review
extra enforces `interrogate` docstring coverage with `fail-under = 80`.
Those numbers are evidence, not a claim that every future module is already
at 100% branch coverage.

## Considered alternatives

- Accept a lower repository-wide percentage: leaves unclassified product
  risk.
- Exclude difficult or optional production files: can hide real behavior.
- Add no-op line execution: raises a number without proving a contract.
- Require owned coverage and beginner-readable public contracts with
  realistic tests: selected.

## Decision

Release acceptance requires owned production statement and branch coverage
where the selected tooling reports each dimension. Unavailable function or
line metrics must be recorded as absent evidence rather than inferred from
another dimension. Public classes, methods, and functions have
beginner-readable docstrings.

Tests exercise observable contracts. When a coverage test exposes a real
HTTP, state, or provider defect, the defect receives a failing regression
before the smallest production repair. Structurally unreachable code is
removed or its invariant is documented; it is not excluded to preserve a
percentage.

Fuzz seams for untrusted-input parsers live in `fuzz/targets.py` and
`tests/fuzz/`. New parsing seams should get a target there.

## Consequences

Every production branch carries a verification and documentation cost.
Reports are more defensible, but complete coverage remains necessary rather
than sufficient: security scans, fuzz, packaging, provenance, independent
review, and protected-main acceptance remain separate gates.

## Failure and recovery

Any missed required coverage or docstring, source-tree mismatch, package
build/install/import failure, or required optional-path gap blocks coverage
acceptance. Recovery adds the real contract test or docstring or reverts the
behavior; it never lowers thresholds or adds a blanket exclusion.

## Security, privacy, and governance impact

Security boundaries receive adversarial, property, and fuzz evidence in
addition to deterministic paths. Fixtures contain no live secrets. Coverage
does not impersonate independent approval.

## Compatibility and migration

Tools may change, but the owned-source set, exact revision, branch
semantics, package smoke, and public API contract remain explicit. Optional
adapters require executable evidence or a clearly non-release status.

## Verification and acceptance

Run focused regressions, the full functional suite, coverage over owned
production, public-docstring inspection, package build/install/import
isolation, property/Atheris seams, and security gates.

## Rollback and supersession

Rollback reverts the production change or supplies the missing real test and
docstring. No rollback weakens the threshold or hides behavior.

## References

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

National Institute of Standards and Technology. (2024b). *Secure software
development practices for generative AI and dual-use foundation models: An
SSDF community profile* (NIST SP 800-218A).
https://doi.org/10.6028/NIST.SP.800-218A

See also [docs/REFERENCES.md](../REFERENCES.md) and
[docs/fuzzing.md](../fuzzing.md).
