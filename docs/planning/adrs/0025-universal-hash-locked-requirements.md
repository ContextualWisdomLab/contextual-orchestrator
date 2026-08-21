---
id: "0025"
title: "Generate one universal hash-locked runtime requirements file"
status: accepted
accepted_date: "2026-08-21"
deciders:
  - "repository maintainer"
affected_components:
  - "requirements.lock"
  - "tests/test_repository_security_metadata.py"
---

# Generate one universal hash-locked runtime requirements file

## Context

The runtime lock is installed with `pip --require-hashes`, but its previous
platform-specific regeneration removed `colorama`, `greenlet`, and `tzdata`.
Those packages are conditional transitive dependencies on supported Python
environments, so a lock produced for one host was not complete evidence for
another host.

## Decision

Generate `requirements.lock` with `uv pip compile --universal
--generate-hashes --python-version 3.10 --extra api --extra db pyproject.toml`.
Universal resolution retains PEP 508 environment markers, one exact version per
resolved branch, and hashes for every artifact while preserving the existing
`pip --require-hashes` installation contract. Regeneration must retain the
platform-conditional `colorama`, `greenlet`, and `tzdata` records and a metadata
test must fail if universal mode or those records disappear.

Do not add a second lock format yet. PEP 751 standardizes `pylock.toml`, but the
current CI and buyer evidence consume the existing requirements file directly.
Adopt `pylock.toml` only when the production installer and security scanners can
consume it without maintaining two divergent dependency authorities.

## Consequences

- macOS, Linux, Windows, architecture, and supported Python marker branches are
  resolved together instead of inheriting the workstation that ran the tool.
- Dependency versions remain auditable and installation remains resolution-free
  under hash-checking mode.
- A regeneration can be more constrained than a host-only solve; an
  incompatible dependency must fail the universal solve rather than silently
  disappear from another platform.

## References

Astral Software, Inc. (2026). *Resolution*. uv.
https://docs.astral.sh/uv/concepts/resolution/

Cannon, B. (2025). PEP 751: A file format to record Python dependencies for
installation reproducibility. *Python Enhancement Proposals*. Python Software
Foundation. https://peps.python.org/pep-0751/

Python Packaging Authority. (2026). *Dependency specifiers*. Python Packaging
User Guide. https://packaging.python.org/en/latest/specifications/dependency-specifiers/
