# PostgreSQL release integration (2026-09-27)

## Structure and gap

This independent release branch integrates the unchanged #1225 owner head
594ea2c8 and #1301 cursor repair into #1300's full license-evidence stack.
Owner branches remain unchanged. Main's fast-mlsirm==0.11.4 pin, uv_build
backend, native build, complete inventory scopes and fail-closed gates remain.

## Exact evidence

Executable source: `04fb595d20cc3179ac7bc8588037b5840f4aa51c`.
`uv lock --check --offline` succeeds. The ten affected DB/inventory/SBOM/
install-gate test files pass 281 tests with process exit 0.

An offline core wheel built at that source has SHA-256
`00a9acfe00ae8b7996db6827f6e509959de8c7b993c3d7ba5e5cf99fd47d9ccf`.
Its metadata retains fast-mlsirm==0.11.4 and replaces psycopg with pg8000.
Pinned canonical archive evidence is reused, not re-downloaded or waived.

| Scope | Packages | Permitted | GPL-family | Undecidable |
| --- | ---: | ---: | ---: | ---: |
| Python including nested distributions | 111 | 92 | 0 | 19 |
| Cargo | 43 | 40 | 0 | 3 |
| npm | 359 | 223 | 0 | 136 |

The prior Python inventory had 109 entries, 88 permitted and two GPL-family
psycopg entries. Removing those two and adding five pg8000 dependencies gives
111 entries. All five new distributions have actual license-text evidence;
the 19 existing holds remain unchanged.

Trivy 0.74.0 with all development scopes and explicit requirements-lock patterns,
followed by the existing strict binder, produces 615 components and 614
dependency rows at this source. No psycopg component remains. These row counts
are inventory projection evidence, not proof of a complete transitive graph.

Local receipts: `/private/tmp/co-pg-integrated-full-inventory-1083.json`,
`co-pg-integrated-bound-sbom-1083.json`, `co-pg-integration-final-tests-1083.log`.
The DB runtime RED/GREEN and real transaction/socket tests are recorded in
[the cursor ownership runbook](pg8000_cursor_ownership.md).

## Remaining acceptance

The 158 undecidable archive entries still block final license acceptance.
No supporting-file, publisher, optional-scope or toolchain exemption is added.
Installed core/native pairing, release container and embedded toolchain
instruments, complete provenance, hosted required gates, immutable publication,
rollback and downstream consumption remain unverified. This branch is an
integration candidate, not a cleared or published release.
