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

## Installed core/native pair verification

At source revision 67dec775, an owned project-local Python 3.12.13 environment
was created with `uv sync --locked --no-editable --extra test --extra db`.
The resulting CO 0.2.0 import comes from site-packages; direct-url metadata
confirms editable=false. fast-mlsirm 0.11.4 imports its released macOS native
extension from the same environment. The standalone wheel SHA-256 remains
`00a9acfe00ae8b7996db6827f6e509959de8c7b993c3d7ba5e5cf99fd47d9ccf`.
All 52 installed wheel files other than RECORD match the wheel bytes exactly.

Tests ran from `/private/tmp`, with only the sibling test-helper directory on
PYTHONPATH and pytest import-mode=importlib. The first command exercised
no-heuristic retry, dispatch boundaries, distinct structured fallback, malformed
synthesis usage, PostgreSQL connection, credential backends/boundaries,
provider catalog storage and bootstrap: 203 tests, exit 0. A second command
exercised passthrough failover, tool fallback, client boundaries and rate-limit
admission: 315 tests, exit 0. No source package root was placed on PYTHONPATH.

The native extension's `chi2_sf(2, 2)` also returned exp(-1) within 1e-12 relative
tolerance. This proves loading and executing that native function, not numerical
estimation accuracy. Exact versions, source/wheel/native hashes and results are
recorded in `evidence/release/1083/installed_core_native_macos.json`.

This is local macOS installed-pair evidence. Linux runtime/container pairing,
complete license and provenance scope, protected main CI, immutable publication
and downstream consumer acceptance remain separate requirements.

## Linux installed pair

The official Python 3.12 bookworm image is pinned to
`sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`,
selected as linux/amd64 and executed through qemu-x86_64 on Colima aarch64.
This is emulated Linux evidence, not bare-metal performance evidence.

An owned container with network=none, all capabilities dropped and
no-new-privileges installed dependencies from retained wheels only, using
uv-exported lock hashes, pip require-hashes/no-index/only-binary. No source
package directory was added to the import path. The installed core and released
fast-mlsirm 0.11.4 extension both load from the container-local venv.

All 52 wheel files except RECORD match the original wheel bytes. The Linux
native extension executed chi2_sf(2,2), matching exp(-1) within 1e-12. The same
13 focused test files then pass 518 tests in 334.61 seconds; both pytest and the
container terminate with exit 0. One PytestCacheWarning reports an unwritable
cache inside the copied test-input directory. It is documented, not suppressed;
this run is not strict-warning or complete-suite acceptance. Future probes
should put pytest cache in the owned writable temporary directory.

`evidence/release/1083/installed_core_native_linux.json` records source revisions,
image, native and wheel digests, driver/requirements/log digests and exact scope.
The earlier driver syntax failure is retained separately from the successful
run. No production/native package defect is inferred from that harness failure.
Full licensing, image/toolchain provenance, protected delivery, publication and
consumer acceptance remain incomplete.
