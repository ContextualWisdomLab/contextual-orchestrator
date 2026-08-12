# Interpreter-Portable Atheris Lock Design

## Status

Approved for autonomous implementation under issue #95. This is a narrowly scoped prerequisite for the repository's same-head coverage and independent-review gates.

## Problem

The repository fuzz job and central coverage-evidence job use different supported CPython minor versions. A single unconditional Atheris pin makes one environment install a release that is not the intended artifact for that interpreter, which prevents coverage evidence from being produced and leaves otherwise repaired security work unmergeable.

## Decision

Use standardized Python dependency environment markers in both project metadata and the hash-locked fuzz requirements:

- CPython below 3.13 selects `atheris==3.0.0`.
- CPython 3.13 and later selects `atheris==3.1.0`.
- Every eligible distribution remains protected by an explicit SHA-256 hash.
- One universal lock remains the source of truth for all supported runners.

No runtime module, provider transport, reviewer identity, secret name, workflow permission, or database object changes.

## Components

### Project metadata

`pyproject.toml` declares both mutually exclusive requirements inside the existing `fuzz` extra. The markers are part of the standardized dependency-specifier language and are evaluated by installation tooling for the active environment.

### Universal hash lock

`fuzz/requirements-atheris.in` records why the interpreter split exists. `fuzz/requirements-atheris.txt` carries the same mutually exclusive markers and the published SHA-256 hashes for the selected Atheris artifacts.

### Contract test

`tests/test_fuzz_dependency_lock.py` reads the metadata and lock as data. It proves:

1. Python 3.11 selects exactly Atheris 3.0.0.
2. Python 3.13 and 3.14 select exactly Atheris 3.1.0.
3. The project markers and lock markers describe the same partition.
4. Every Atheris lock entry has at least one SHA-256 hash and the expected published hashes are present.
5. No interpreter selects zero or multiple Atheris releases.

The test performs no network access and does not import Atheris.

## Failure semantics

Malformed, overlapping, incomplete, or unhashed requirements fail the normal test suite. Installation remains fail-closed through `--require-hashes`; this change does not introduce an unhashed fallback.

## Documentation and release evidence

`docs/doctoring/atheris-interpreter-lock.md` records the packaging specification and artifact evidence with APA 7 references. `CHANGELOG.md` records the compatibility change under `Unreleased`.

## Non-goals

- changing fuzz targets or fuzz budgets;
- changing provider egress or security behavior;
- changing the existing OpenCode review-agent credential scheme;
- changing scheduled workflows;
- upgrading unrelated dependencies.
