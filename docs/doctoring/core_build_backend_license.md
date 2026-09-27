# Core build backend and bundled LGPL repair

## Structure and defect

The core wheel contains Python code; the decision measurement extension ships
in its separately verified maturin wheel. The core build backend and the
hash-pinned CI quality-tool input both selected setuptools. The staged
setuptools 84.0.0 wheel declares MIT at its root but contains
`setuptools/_vendor/autocommand-2.2.2.dist-info/METADATA` declaring LGPLv3 and
its corresponding LICENSE. Ignoring nested metadata would hide that component.
The current strict reader still holds the wheel; its identity exception is not
proof that all included libraries are permissively licensed.

## Repair

Reuse the already installed, pinned uv 0.12.5 native build backend for the pure
Python core. Keep the existing maturin extension distribution separate. Explicit
module-root/name and native-file exclusions preserve the ownership boundary.
The core's MIT expression and exact licence file remain in built metadata.
Replace the setuptools CI pin with uv_build 0.12.5; add the backend to the
native-build group so it remains a declared, hash-locked inventory scope for
other frontends. Regenerate locks without executing dependency builds.

The existing CI wheel command now uses offline uv build with build isolation
turned off. Existing uv supplies the compatible backend; building this proof
installed no project/backend dependency and made no provider request.
The metadata regression builds a real wheel with a temporary `.so` file present
and proves that it does not enter the core wheel. It inspects the complete MIT
file bytes. Missing/incompatible tooling fails rather than skipping the proof.

## Evidence and limits

At predecessor ea08306d plus the candidate backend delta, the local offline build
included all 47 source Python modules, 55 wheel files, correct name/version/MIT
metadata and no `.so`/`.pyd` ownership overlap. The build is layout/metadata
proof, not the current-main release artifact or native-pair runtime acceptance.
171 focused metadata, benchmark workflow, inventory/licence/SBOM/security/release
contracts passed (process exit 0); actionlint/diff checks passed. The inherited
minimal pytest asyncio configuration warning remains. Lock regeneration added
only uv-build to the project resolution and removed setuptools from the active
CI-tool lock. No dependency build ran during resolution (`uv lock --no-build`).

The candidate macOS uv_build wheel SHA-256 is
292b2bf9eeb9b304974efad64ef26702c7133a641d2ac2b893201542c2909426,
verified against its exact PyPI artifact record. Its own MIT/Apache licence
texts pass the existing artifact classifier. Its embedded CycloneDX lists 257
Rust components and no GPL-family declaration. This is **not** complete licence
instrument/provenance adjudication of every compiled component or every platform
artifact. Preserve that bundled-scope gap, other publisher holds, final root
wheel staging, complete hosted gates, immutable release and downstream acceptance.
No licence gate or strict nested-metadata refusal is relaxed by this repair.

Local receipts: `/private/tmp/co-bundled-python-metadata-1083.json`,
`co-uv-build-candidate-license-1083.json`, and
`co-uv-core-wheel-candidate-receipt-1083.json`, with matching build/download logs.

## Alternatives and primary references

Downgrading below setuptools' PEP 639 support loses the required expression
contract and does not establish a security-safe version. Latest setuptools 84
still bundles the observed LGPL library. A new backend framework is unnecessary
for this core layout: uv already provides the required build functionality.

- [Upstream bundled licence issue](https://github.com/pypa/setuptools/issues/5049)
- [uv backend, layout and bundled implementation](https://docs.astral.sh/uv/concepts/build-backend/)
- [PEP 639 metadata guidance](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license-and-license-files)
