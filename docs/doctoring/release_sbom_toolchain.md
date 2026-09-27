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
