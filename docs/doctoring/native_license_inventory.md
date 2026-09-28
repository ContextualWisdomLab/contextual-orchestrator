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
