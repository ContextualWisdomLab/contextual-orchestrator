# Atheris interpreter lock evidence

## Decision record

Contextual Orchestrator uses one universal, hash-locked fuzz dependency file across validation environments. The repository fuzz runner uses CPython 3.11, while central coverage evidence can run on CPython 3.13 or later. The lock therefore partitions Atheris releases with standardized Python environment markers rather than maintaining divergent unreviewed lock files.

## Standards basis

The Python Packaging dependency-specifier specification defines environment markers as conditional dependency rules evaluated for the active installation environment. `python_version` and `python_full_version` are version-typed marker fields, and ordered comparisons such as `<` and `>=` use version-specifier semantics. Mutually exclusive markers are therefore the portable standards-based mechanism for selecting one interpreter-compatible dependency release.

The project metadata uses:

```text
atheris==3.0.0; python_version < "3.13"
atheris==3.1.0; python_version >= "3.13"
```

The generated universal requirements lock expresses the equivalent boundary with `python_full_version`, preserving installation-tool compatibility while selecting exactly one Atheris release.

## Artifact evidence

PyPI records Atheris 3.0.0 artifacts for CPython 3.11 through 3.13 and Atheris 3.1.0 artifacts for CPython 3.12 through 3.14. The repository retains 3.0.0 for its established Python 3.11 fuzz runner and selects the newer 3.1.0 release for Python 3.13 and later coverage environments.

The lock includes the published SHA-256 values used by the supported manylinux wheels and source distribution evidence:

### Atheris 3.0.0

- `1f0929c7bc3040f3fe4102e557718734190cf2d7718bbb8e3ce6d3eb56ef5bb3`
- `510e502c57b6dc615fb174066407af620d4c7f73cf08a782c86e7761bf12c4eb`
- `8a5c8a781467c187da40fd29139784193e2647058831f837f675d0bb8cbd8746`
- `a402cdca8a650d1371050b1f9552eb4cdc488d2db64950d603c4560318365eac`

### Atheris 3.1.0

- `315a0b5c819852b1ffe1ca72efc389c7724881f2c33e4aacb8c6bcec49bd5011`
- `ec5e11f21a4c197fe91f7aea2b2de88e623c73a21fc07b105ac6329a1588457b`
- `f8a9f51ce8369026e8eb7b7174835e8c4c85a1a6db5d9add36c15100779d2a39`

Installation continues to use `--require-hashes`; no unhashed or network-selected fallback is introduced.

## Verification contract

`tests/test_fuzz_dependency_lock.py` treats project metadata and the universal lock as evidence. It evaluates representative Python 3.11, 3.13, and 3.14 environments and fails when requirements overlap, leave an interpreter uncovered, disagree between metadata and lock, or omit published SHA-256 evidence.

The test does not import Atheris or use provider egress. It therefore remains deterministic and can run before the platform-specific wheel is installed.

## CI trust boundary

The generic repository coverage verifier and the native fuzz runner have different responsibilities. Generic coverage must materialize the exact current lock identity or report a blocker; it must never accept an older lock-key artifact or silently fall back to an unhashed installation. Native Atheris execution remains isolated in the dedicated fuzz workflow so a platform-specific fuzz engine cannot make ordinary statement, branch, docstring, or package evidence non-portable.

When a centrally maintained reusable workflow is referenced by a mutable branch and its verifier is repaired, retry semantics matter. GitHub documents that re-running only failed jobs retains the called reusable workflow commit from the first attempt, while re-running all jobs resolves the workflow from the specified branch reference. Operators must therefore use a fresh pull-request event or an all-jobs rerun when validating a central workflow repair, and must record the resulting current-head workflow identity. An older failed-job retry is not evidence for the repaired verifier.

## Applicability and uncertainty

This record proves dependency-selection and artifact-integrity consistency for the repository's declared interpreter partition. It does not claim that every operating system or architecture has an Atheris wheel. Runners outside the documented Linux/CPython environments must perform their own artifact-availability review and must not remove `--require-hashes` to force installation.

Artifact availability and hashes are time-sensitive upstream facts. They were rechecked on August 5, 2026. Future version changes require a new lock regeneration, focused contract update, and renewed evidence review.

## APA 7 references

GitHub. (2026). *Reusing workflow configurations*. GitHub Docs. https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

Google. (2025). *Atheris* (Version 3.0.0) [Computer software]. Python Package Index. https://pypi.org/project/atheris/3.0.0/

Google. (2026). *Atheris* (Version 3.1.0) [Computer software]. Python Package Index. https://pypi.org/project/atheris/3.1.0/

Python Packaging Authority. (2026). *Dependency specifiers*. Python Packaging User Guide. https://packaging.python.org/en/latest/specifications/dependency-specifiers/
