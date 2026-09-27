# Cargo/npm license evidence collection

## Collection defect and repair

PR #1226's inventory enumerated all native lock entries, but discarded Cargo
checksums and npm integrity/source fields and attached license evidence only to
Python entries. Its snapshot contains 43 Cargo and 359 npm entries; none had
`licenses` or `license_files`. This was a collector defect, not evidence that
those packages were permitted or prohibited.

The successor retains native lock digests and reads `.crate`/`.tgz` archives
without extraction, installation, imports, build scripts or install hooks.
Only the canonical crates.io/npm registry sources are supported. Redirects,
custom sources, missing strong digests, changed archive bytes, mismatched
package identities, links, unsafe paths and duplicate evidence are refused.
Npm tarballs may use any single top directory; the lock digest and package.json
identity establish the package, not the conventional `package/` directory name.
The full live scan exposed this case in DefinitelyTyped archives, and the
reader and regression checks were corrected before publication.
Unknown or restricted licenses still fail the existing classifier.

Archive evidence includes the complete publisher declaration, bundled license
and notice text, archive digest and each text's digest. Cargo's explicit
`license-file` is read even when its filename is unconventional. Local workspace
members use their committed manifest declaration and committed license file;
their evidence joins the inventory's source-blob checks. The two project crates
now explicitly declare the repository's existing MIT license.

Reads are bounded at 256 MiB compressed, 2 GiB expanded, 100000 entries and
4 MiB per selected text. Exceeding a bound is a hold, never a scope exemption.
The current pnpm v9 inline `resolution: {integrity: ...}` form is supported;
another form remains unresolved instead of guessing its digest. Conflicting
npm lock digests fail before deduplication.

## Reproduction

```bash
python -m scripts.ci.dependency_inventory --repository-root . \
  --output /dev/null --check-sources-only
python -m pip download --require-hashes -r requirements.lock \
  --no-deps --only-binary=:all: --dest license-artifacts
python -m scripts.ci.dependency_inventory --repository-root . \
  --output dependency-inventory.json --artifact-dir license-artifacts \
  --download-native-artifacts
python -m scripts.ci.release_license_gate --inventory dependency-inventory.json \
  --source-sha "$(git rev-parse HEAD)" --mode preinstall
```

The release post-build gate reuses the same staged archives. Collection alone
is not adjudication; all unknown/copy-left entries stop publication. Downloaded
Python wheels still must cover the complete Python inventory, including build,
dev and fuzz scopes. The inherited external Python source refusal and other
security jobs that install before this supply-chain job remain separate gaps.
This repair does not assert that the whole CI fleet executes only adjudicated
packages, or that the installed-environment SBOM is complete.

## Evidence

Focused inventory/classifier/workflow regressions cover both native ecosystems,
optional/dev packages, both npm locks, local workspace source provenance,
checksum/identity failures, missing text, late copyleft clauses, traversal,
links, duplicate evidence, evidence limits, registry redirect refusal and owned
HTTP-error closure. Keep process exit separate from test-body output.

A non-executing live check on 2026-09-27 verified locked pyo3 0.29.2 (MIT OR
Apache-2.0; four bundled license files) and react 19.2.8 (MIT; one license file)
against their archive digests. Both passed the existing classifier. This is a
two-package transport/reader receipt, not an all-dependency clearance or
release acceptance. Full inventory adjudication and hosted checks remain required.

Official metadata contracts: [Cargo manifest](https://doc.rust-lang.org/cargo/reference/manifest.html#the-license-and-license-file-fields),
[npm lockfile](https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json/),
[npm archive layout](https://docs.npmjs.com/cli/v11/commands/npm-install/#description).

The completed full native scan at collector head `f55915af` read all 400
registry archives plus both local crates. The unchanged classifier permitted
41/43 Cargo and 212/359 npm entries, holding the rest. Cargo holds were
`target-lexicon` (the LLVM exception mentions GPLv2, triggering the existing
blanket text matcher) and `tiktoken-rs` (no bundled license text). Npm holds
comprised 116 declarations without bundled text, 12 without declarations
(the OpenCode platform packages), and 19 declaration/text holds (MPL,
CC-BY and BlueOak declarations). These require policy/publisher evidence
repairs, not invented permissive terms or dropped optional/dev scope.

All 122 Python entries were intentionally held in this native-only scan because
no Python wheels were staged. That count is not a Python license verdict.
The combined inventory/classifier/workflow/install-gate command passed 175
tests with exit 0; one inherited minimal-interpreter pytest config warning
remained. Actionlint and diff checks passed. No hosted or release acceptance
is inferred from these local results.

Native scan `full-inventory.json` SHA256: `8aad87013314e782d813865552e644797bb49bfb491f265c6e13b4ead707f887`.

Native scan `full-classification.json` SHA256: `d8a491278a94f7c78c813bf62f0806297fc41b6b9ab61beb4cddc5edb776d4a4`.

## Publisher and Python artifact follow-up (2026-09-27)

`tiktoken-rs` 0.7.0 really omits the license instrument: its explicit package
include list contains assets, source and README only. Its archived VCS record
names commit `7c20dc69d6d71efceecd20daa7067fa92edea3ba`; that revision's root
MIT text has SHA256 `f7c6ddf9d84fd7b8ad5917e4074d4c05e4c1dfb752a28a0058f06bd0f5e2edcc`.
This is not enough to prove binary/archive provenance: Cargo documents the VCS
record as best-effort, not verified. The shipped 0.7.0 archive stays held.

Upstream main `72a5a800651a1cea1ad609292446ba02c80e3bcd` still omits the file.
An isolated one-line repair, `license-file = "../LICENSE"`, changed
`cargo +1.98.0 package --list --offline` from 20 files without LICENSE to 21
with LICENSE. A real `cargo package --allow-dirty --no-verify` then produced
an unpublished 0.12.1 archive with that exact root license text. Package code
was not built or run. Offline archive creation failed on an uncached optional
index entry; ordinary index resolution followed by no-verify packaging exited
0. This is packaging proof, not a published dependency replacement or API
compatibility proof. No third-party archive/checksum was rewritten. Posting
that patch to the external upstream awaits explicit messaging authorization.

On protected-main snapshot `aaa4dfdd9d3744f303436ae23e67cf0e06536347`,
requirements.lock and requirements-security-ci.txt were downloaded with
`pip download --require-hashes --no-deps --only-binary=:all:` for CPython 3.12
Linux wheels. Nothing was installed. Of the complete 121-entry Python union,
65 were permitted, 3 carried GPL-family declarations and 53 remained held
(unstaged or unmatched evidence). The three declared findings are psycopg,
psycopg-binary (the existing #1225 owner) and chardet 5.2.0 in the security
CI toolchain. CI-tool scope is not exempted. This is not all-Python clearance.

The wheel reader previously selected a longer-version filename prefix and
accepted another distribution's metadata/instrument or the first of multiple
wheel variants. Five RED cases reproduced these defects. The repair requires
an exact filename version boundary, one wheel and one METADATA record,
matching normalized Name/exact Version, and license files under that same
distribution's metadata root. All inventory callers use the repaired reader.
The combined inventory/classifier/workflow/install-gate command passed 199
tests, exit 0, with the inherited minimal-interpreter config warning retained.
No hosted or release acceptance is claimed.

Primary contracts: [Cargo package and VCS limitations](https://doc.rust-lang.org/cargo/commands/cargo-package.html),
[Python wheel metadata layout](https://packaging.python.org/en/latest/specifications/binary-distribution-format/).
