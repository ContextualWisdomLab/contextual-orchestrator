# Bundled Python distribution evidence

## Structure and gap

A wheel can contain its root distribution and separate vendored `.dist-info`
records. The single-distribution reader deliberately refuses that shape; simply
ignoring nested records would have hidden setuptools' LGPL autocommand dependency.
The release inventory now reads every record, preserves its own name/version,
metadata path and SHA-256, complete licence text and whole-wheel SHA-256, and adds
bundled identities to the Python scope. Root terms never certify a bundled record.
The strict single-distribution API still refuses multiple records.

One top-level root must match the requested wheel identity. Duplicate archive
paths, path traversal, unowned licence files, contradictory metadata directories,
and metadata inside another distribution's evidence directory are refused.
Declared `License-File` paths are also read even when named `EULA.txt`; missing,
unsafe or ambiguous declarations fail. Archive and text reads reuse the existing
bounded evidence limits. Nothing is
extracted, installed or imported.

## Measurement and verification

The hash-staged `py==1.11.0` wheel contains separately owned MIT instruments for
`py`, `apipkg==2.0.0` and `iniconfig==1.1.1`. The shared classifier accepts all
three independently. MIT root plus LGPL child and undeclared child controls
retain the child findings. Production collection keeps both nested identities.

Reusing the complete staged Python/Cargo/npm artifacts produces 109 Python,
43 Cargo and 359 npm records. Python: 93 permitted, 2 GPL-family, 14 held;
Cargo: 40 permitted, 3 held; npm: 223 permitted, 136 held. These are current
classifier results, not legal clearance or release acceptance. Stricter owner
text checks retain additional holds rather than reusing older weaker results.

Trivy 0.74.0 source scanning plus the bound inventory produces 610 components
and 609 dependency rows. The binder adds both bundled components with distinct
references, wheel/metadata digests, metadata paths and edges from their actual
parent wheel. A forged parent digest fails. Existing dependency edges remain.
This proves component projection and parent ownership, not every transitive
edge, dependency lacking distribution metadata, embedded Rust SBOM instruments,
container layers, installed runtime or hosted release acceptance.

```sh
python -m pytest -q tests/test_dependency_inventory.py \
  tests/test_release_license_gate.py tests/test_release_sbom.py \
  tests/test_security_workflow_install_gate.py \
  tests/test_python_license_artifact_collection.py
```

Local receipts: `/private/tmp/co-py-bundled-instruments-1083.json`,
`co-py-bundled-projection-1083.json`, `co-bundled-full-inventory-1083.json`,
`co-bundled-full-classification-1083.json`, and
`co-bundled-current-bound-sbom-1083.json`. These bind staged artifact bytes and
candidate collector behavior, not a released immutable revision.
