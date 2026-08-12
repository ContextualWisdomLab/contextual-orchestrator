# Interpreter-Portable Atheris Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hash-locked Atheris fuzz dependency install deterministically across the repository's supported Python 3.11 and Python 3.13+ validation environments.

**Architecture:** Keep one universal requirements lock and partition Atheris versions with standardized Python environment markers. Add a no-egress contract test that treats project metadata and the lock as immutable evidence and rejects gaps, overlap, or missing hashes.

**Tech Stack:** Python 3.10+, `tomllib`, `pytest`, PyPA dependency specifiers, uv-generated hash locks.

## Global Constraints

- Do not modify provider transports, runtime behavior, reviewer identities, reviewer secrets, or workflow permissions.
- Keep `--require-hashes` compatibility and explicit SHA-256 artifacts.
- Add explanatory docstrings to every new helper and test.
- Document current authoritative sources in `docs/doctoring/` using APA 7 references.
- Update `CHANGELOG.md`.
- Use only descriptive multi-word snake_case names for new data or database objects; this slice creates no database object.

---

### Task 1: Add the failing dependency-lock contract

**Files:**
- Create: `tests/test_fuzz_dependency_lock.py`

**Interfaces:**
- Consumes: `pyproject.toml`, `fuzz/requirements-atheris.txt`
- Produces: deterministic assertions for interpreter selection and hash completeness

- [ ] **Step 1: Write a test that expects two mutually exclusive Atheris requirements**

The test must load the `fuzz` extra with `tomllib`, parse the two exact Atheris entries, and evaluate representative Python 3.11, 3.13, and 3.14 environments.

- [ ] **Step 2: Write a test that verifies lock markers and published hashes**

Require the lock to contain the 3.0.0 and 3.1.0 entries with matching interpreter partitions and at least one SHA-256 hash per entry.

- [ ] **Step 3: Run the focused test and verify RED**

Run: `python -m pytest tests/test_fuzz_dependency_lock.py -q`

Expected: FAIL because the Python 3.13+ project requirement and lock entry do not yet exist.

- [ ] **Step 4: Commit the failing contract**

```bash
git add tests/test_fuzz_dependency_lock.py
git commit -m "test(fuzz): require interpreter-portable Atheris lock"
```

### Task 2: Partition the fuzz extra by interpreter

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `atheris==3.0.0; python_version < '3.13'` and `atheris==3.1.0; python_version >= '3.13'`

- [ ] **Step 1: Add the Python 3.13+ requirement**

Keep the existing pre-3.13 marker and add the mutually exclusive 3.1.0 marker.

- [ ] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_fuzz_dependency_lock.py -q`

Expected: the metadata assertion passes; the lock assertion remains RED.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build(fuzz): partition Atheris by interpreter"
```

### Task 3: Regenerate the universal hash lock

**Files:**
- Modify: `fuzz/requirements-atheris.in`
- Modify: `fuzz/requirements-atheris.txt`

**Interfaces:**
- Consumes: the project interpreter partition
- Produces: one hash-locked requirements file valid for all supported runners

- [ ] **Step 1: Document the interpreter split in the input file**

Explain the repository Python 3.11 fuzz runner and newer coverage-evidence interpreter without referring to secret values or mutable runner identity.

- [ ] **Step 2: Add the 3.1.0 lock entry and published hashes**

Use the exact version markers and SHA-256 values recorded in the doctoring evidence.

- [ ] **Step 3: Run the focused test and verify GREEN**

Run: `python -m pytest tests/test_fuzz_dependency_lock.py -q`

Expected: PASS.

- [ ] **Step 4: Run the complete repository gates**

Run the repository's documented Tests and Fuzz commands, followed by compilation and package-install smoke tests.

- [ ] **Step 5: Commit**

```bash
git add fuzz/requirements-atheris.in fuzz/requirements-atheris.txt
git commit -m "build(fuzz): lock Atheris for supported interpreters"
```

### Task 4: Record evidence and release notes

**Files:**
- Create: `docs/doctoring/atheris-interpreter-lock.md`
- Create: `CHANGELOG.md`

**Interfaces:**
- Produces: source-backed operational rationale and Unreleased change evidence

- [ ] **Step 1: Add the doctoring record**

Record the PyPA environment-marker specification, Atheris release artifacts, hash provenance, uncertainty boundary, and APA 7 references.

- [ ] **Step 2: Initialize the changelog**

Use Keep a Changelog structure and add the interpreter-portable lock under `Changed`.

- [ ] **Step 3: Run documentation and full validation gates**

Run formatting, tests, fuzzing, security, SAST, package build/install smoke tests, and docstring gates.

- [ ] **Step 4: Commit**

```bash
git add docs/doctoring/atheris-interpreter-lock.md CHANGELOG.md
git commit -m "docs(fuzz): record interpreter-portable lock evidence"
```

### Task 5: PR validation and integration

**Files:**
- No new source files

**Interfaces:**
- Produces: a mergeable prerequisite for PR #76

- [ ] **Step 1: Open a focused PR closing issue #95**

- [ ] **Step 2: Review every automated and human finding**

Apply only validated fixes, preserve the narrow scope, and rerun exact-head checks.

- [ ] **Step 3: Merge only after all required checks and reviews pass**

- [ ] **Step 4: Update PR #76 to the new main and rerun its exact-head coverage evidence**
