# Release SBOM toolchain repair

## Structure and gap

Security installs `requirements-security-ci.txt`, audits the project lock and
uploads `cyclonedx-sbom.json`; release verification retrieves that artifact from
a successful push run at the exact source SHA. The installed-environment
CycloneDX CLI omitted declared native, development, build and platform scopes.
Its mandatory `chardet>=5.1,<6` dependency also introduced LGPL-2.1-or-later:
requests only lists chardet as an optional extra, so requests was not the cause.
The current upstream CycloneDX CLI 7.3.1 still requires that dependency.

## Repair and verification

Reuse the organization's existing Trivy scanner, pinned to release 0.74.0 and
setup action 3fb12ec12f41e471780db15c232d5dd185dcb514. Include development packages
and the custom hash-pinned CI requirements files. Retain the separate pip-audit
vulnerability gate, full inventory and preinstall licence gate. Regenerate the
security tool lock from its input after removing cyclonedx-bom; do not override
or discard a mandatory transitive dependency.

`release_sbom` checks every declared Python/Cargo/npm name and version, refuses
empty scopes and wrong source identities, checks component fields against their
package URLs and retains the scanner's dependency graph. It copies publisher
licence declarations from the separately adjudicated inventory where absent;
these names are not legal approval or invented SPDX expressions. Source SHA
and a SHA-256 of canonical inventory JSON bind the two artifacts together.
Canonical JSON is UTF-8, sorted keys, comma/colon separators and no newline.

At main aaa4dfdd9d3744f303436ae23e67cf0e06536347, Trivy's default output omitted
packages and was refused. `--include-dev-deps` plus
`--file-patterns 'pip:requirements.*\.(txt|lock)$'` produced 678 components and
679 dependency rows. Its unique package identities covered all 121 Python,
43 Cargo and 359 npm inventory entries, including optional platform packages.
Duplicate components from separate lockfiles are retained with their graph
references. These measurements are component coverage, not a claim that every
transitive edge or licence instrument is known.

31 focused SBOM/security/release supply-chain contracts passed; actionlint and
diff-check passed. The inherited minimal test environment reports its existing
unknown asyncio configuration warning. Missing package controls cover build,
Cargo and npm platform scopes, plus wrong source/empty inventory/forged version.

Local receipts are retained under `/private/tmp/co-trivy-sbom-*-1083.json`,
`co-trivy-source-inventory-1083.json` and matching logs. These are local evidence;
no hosted acceptance, complete licence clearance, reproducible wheel, immutable
release or downstream consumer acceptance is claimed. The remaining publisher
licence holds and any unenumerated external tool supply chain still require
adjudication before release. The existing owners' review branches remain intact.

## Primary references

- [CycloneDX CLI dependencies](https://github.com/CycloneDX/cyclonedx-python/blob/main/pyproject.toml)
- [Trivy SBOM generation](https://trivy.dev/docs/latest/supply-chain/sbom/)
- [Trivy release 0.74.0](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0)
- [Existing pip-audit CycloneDX formatter](https://github.com/pypa/pip-audit/blob/v2.10.1/pip_audit/_format/cyclonedx.py)

The pip-audit formatter was considered and rejected as a replacement: it emits
package names/versions and vulnerability rows but omits the richer dependency
graph and publisher licence metadata. Reusing Trivy avoids a new SBOM collector.

## Duplicate input follow-up

A subsequent full Python artifact survey found that the unused historical
`requirements-security-tools.in` still declared unpinned `cyclonedx-bom` and its
hash lock retained chardet. No workflow, executable script or build target reads
that pair; current Security uses the exact-pinned `requirements-security-ci`
input/lock. Remove the obsolete pair instead of pretending its declared packages
are exempt. Keep the inventory's enumeration of every remaining requirements
file, and assert that no tool input reintroduces the mandatory LGPL CLI.

The survey staged 122 hash-validated wheels without installing or importing
package code. At main aaa4dfdd, individual reads yielded 93 permitted, 3 declared
GPL-family and 25 unresolved Python entries. The three are chardet and the
psycopg pair; #1225 owns the latter. Vendored metadata in py and setuptools is
currently held by the strict wheel identity reader, not proof of a publisher
licence violation. Source-package prebuild evidence, missing instruments,
canonical text variants and wheel-bundled dependency scope remain separate work.

## Root-project prebuild evidence

The uv lock identifies this repository's own root as `source={virtual="."}`;
editable root distributions use `source={editable="."}`. Before building, the
root project has no released wheel to download. Looking only in staged wheels
therefore makes its source licence hold indefinitely.

The explicit `--prebuild-local-project` option reads the committed root
pyproject name/version, SPDX declaration and every matching licence file. Blob
provenance and text digests remain part of the same inventory. Wrong identity,
outside paths, missing files and dirty blobs cannot authorize installation.
Only those two exact root source markers qualify; an identically named registry
package must still supply its own wheel evidence. No package source is built or
executed to inspect these files.

Security and release use the option only before install. Default collection
continues to demand a wheel, and the final release gate refuses inventories
marked `prebuild-source`; source evidence cannot substitute for built-package
proof. The final release path must stage the exact built root wheel separately.
That remaining staging requirement and other publisher/bundled licence holds
remain open; this repair does not claim publication readiness.

At exact main aaa4dfdd, the existing collector found no root wheel and the
manifest lacks the required string declaration/file list, so the new source
reader correctly keeps it held. On this successor stack at 29df7084, #1226's
committed MIT declaration and LICENSE pass prebuild classification with blob
checks. Receipts: `/private/tmp/co-prebuild-project-license-receipt-1083.json`
and `/private/tmp/co-prebuild-project-license-stack-receipt-1083.json`.
159 focused contracts passed, plus the registry identity control passed
separately; actionlint/diff checks passed. The existing minimal pytest config
warning remains. Controls include virtual/editable roots, dirty licence bytes,
wrong identity, escaping/missing files and explicit final-release refusal.

[PyPA licence metadata guidance](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license-and-license-files)
provides the string declaration and licence-file pattern contract.

## Python artifact collection scope repair (2026-09-27)

The preinstall workflow previously downloaded only `requirements.lock`, while
its inventory included `uv.lock` plus every root and fuzz `requirements*.txt`.
The missing wheels were missing evidence, not permission to omit those scopes.
Both Security and release now reuse `collect_python_license_artifacts.sh`: it
exports all groups and extras from the locked offline uv resolution, excludes
only the root project (whose committed source is checked before its wheel
exists), refuses external sources in the export, and downloads every independent
hash lock separately. Binary-only, hash-required downloads do not install
packages or execute their build backends. A download failure stops the job
before adjudication or installation.

This collects the current runner's compatible wheels. Platform markers can
exclude another platform's artifact; the complete inventory still includes it
and keeps that identity unresolved. Bundled distributions, container image
layers and unknown native instruments remain separate publication requirements.
The final release gate still reads the exact built root wheel, never prebuild
source evidence. Export options: [uv CLI reference](https://docs.astral.sh/uv/reference/cli/#uv-export).

## Installation markers versus licence scope (2026-09-27)

The first shared collector retained installation markers, so Linux omitted
`tzdata` even though the complete inventory required its evidence. The collector
now validates each source before creating temporary evidence-only requirement
copies. It removes environment markers from pinned requirement lines in those
copies, preserving the version, continuation and every locked hash. Original
lockfiles and installation semantics stay unchanged. No optional or unexecuted
package is exempted. Binary-only downloads and missing-wheel failures remain.

Conflicting conditional versions in one scope still fail dependency resolution,
rather than selecting one and shrinking the inventory. A future lock with that
shape needs separate artifact collection per exact identity before publication.
This does not establish all-platform bundled licensing or runtime compatibility.
