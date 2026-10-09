# Lockfile Version Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve exact installed package versions from supported npm and Cargo lockfiles without authorizing a vulnerability finding before an affected-range evaluator exists.

**Architecture:** Extend the existing bounded snapshot reader with one lockfile-only evidence function. Expose immutable version/provenance fields on `VulnerabilityClaimVerdict`; retain `versions_checked=false`, `finding_allowed=false`, and `unverified` until a separately reviewed ecosystem range evaluator is present.

**Tech Stack:** Python 3.12 stdlib, pytest, npm package-lock v2/v3, Cargo.lock.

**Spec:** `docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md`

## Global Constraints

- No search ranking, caller package list, manifest range, or heuristic parser may authorize a finding.
- Read only regular, non-symlink files below the operator-selected snapshot.
- npm evidence must come from non-link registry package rows in `package-lock.json`; Cargo evidence must come from `Cargo.lock` package rows.
- Missing, malformed, or unsupported lock evidence fails closed.

## Review Focus

- npm manifest ranges without a lockfile must not become installed-version evidence.
- npm link, git, local, and non-registry rows must not become registry-version evidence.
- One package may have multiple installed lockfile versions; preserve all unique versions deterministically.
- Cargo manifest requirements must not become installed-version evidence.
- Invalid lockfile row types must fail closed rather than leaking partial evidence.

---

### Task 1: Exact lockfile evidence

**Files:**
- Modify: `contextual_orchestrator/vulnerability_claim.py`
- Test: `tests/test_vulnerability_claim.py`
- Modify: `docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md`
- Modify: `docs/product-technical-gap-baseline.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: operator-selected repository snapshot and existing package canonicalization.
- Produces: `_repository_installed_versions(ecosystem: str) -> dict[str, tuple[str, ...]]`; additive verdict fields `installed_versions` and `version_evidence`.

- [x] **Step 1: Write failing npm and Cargo lockfile tests**

Assert exact unique versions and provenance are returned while `versions_checked` and `finding_allowed` remain false; assert manifest-only inputs produce no installed versions.

- [x] **Step 2: Verify RED**

Run: `uv run python -m pytest tests/test_vulnerability_claim.py -q -W error`

Expected: FAIL because the fields/function do not exist.

- [x] **Step 3: Implement the minimal lockfile reader and additive verdict fields**

Use the existing bounded file reader. Do not parse advisory ranges or add a dependency.

- [x] **Step 4: Verify GREEN and regression scope**

Run the focused vulnerability/MCP suites, Ruff for touched Python files, compileall, and `git diff --check`.

- [x] **Step 5: Update ADR, Gap baseline, and changelog with exact evidence boundaries**

Record npm/Cargo authoritative lockfile references and state that affected-range evaluation remains the next blocked source lane.
