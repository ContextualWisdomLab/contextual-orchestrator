# Bundled archive license scope (2026-09-27)

## Structure and RCA

The #1304 metadata gate holds python-dateutil's ambiguous Dual License label.
Its exact wheel a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427
also includes dateutil/zoneinfo/dateutil-zoneinfo.tar.gz, a 156400-byte archive
with 619 members. Its own METADATA names tzdata2024a and a source SHA-512.
Root code-license evidence alone cannot settle this separate data scope.
An uncommitted root-instrument adjudication experiment was discarded before
publication; no ambiguous marker or package exception was retained.

The collector now records each recognizable archive payload's exact path,
SHA-256 and size without unpacking or executing it. Binary reads are streamed
and bounded by the existing archive limit before opening the entry. The release
gate holds a component containing any such unresolved archive, retaining GPL
classification precedence. Unknown contents never inherit parent permission.

## Verification

A root-MIT wheel with an unseen nested archive reproduces missing scope evidence
before the repair. Afterward the five affected inventory/license/SBOM/install
files pass 189 tests (exit 0). The nested-identity and pre-read expanded-size
limit controls additionally pass both cases. Existing archive, ownership,
metadata and GPL controls remain enabled.

The exact IANA source identified by the nested metadata was retrieved from
https://data.iana.org/time-zones/releases/tzdata2024a.tar.gz; its bytes match
SHA-512 1f09f1b2327cc9e1afc7e9045e83ee3377918dafe1bee2f282b6991828d03b3c70a4d3a17f9207dfb1361bb25bc214a8922a756e84fa114e9ba476226db57236.
The source LICENSE declares the default public-domain scope and names three
conditional BSD exceptions. This establishes the claimed source artifact's
identity and instrument. The reproduction below separately verifies the timezone member bytes.
[IANA database and release documentation](https://data.iana.org/time-zones/tz-link.html).

## Acceptance gap

The exact 598 timezone paths and their complete member bytes were reproduced
with IANA zic 2019b and the wheel's recorded 2024a source and eleven input groups.
Native zic 2022g and zic 2024a match only 396 paths: their TZif output omits an
older compatibility transition at 2**31-1. The verifier returns failure for
that mismatch rather than treating similar output as identical.

The committed receipt records source, wheel, embedded archive and compiler
hashes, build arguments and verification scope. Reproduction does not identify
the historical producer. METADATA and tar/gzip serialization are excluded.
Per-member ownership, license-instrument projection and complete SBOM child
scope remain unverified. The payload remains
held. Archive-suffix detection is not a universal binary format detector; a
complete release must also account for hidden formats, vendor code, toolchain
and container layers. No parent license, filename, development scope or publisher
waiver is added. Full release and downstream acceptance remain incomplete.

```sh
uv run --locked --extra test python -m pytest -q tests/test_dependency_inventory.py \
  -k 'bundled_archive_has or nested_archive_size'
```

## Repeat the byte comparison

Build zic from the public-domain IANA 2019b source using an existing C compiler;
do not install it into a system path. The receipt in
`evidence/release/1083/dateutil_zoneinfo_reproduction.json` records the exact
compiler source SHA-512, build arguments and compiler version.
[IANA compiler source](https://data.iana.org/time-zones/releases/tzcode2019b.tar.gz).

```sh
python scripts/ci/verify_dateutil_zoneinfo_reproduction.py \
  --wheel /path/to/python_dateutil-2.9.0.post0-py2.py3-none-any.whl \
  --tzdata /path/to/tzdata2024a.tar.gz --zic /path/to/zic-2019b \
  --output /path/to/reproduction.json
```

Exit 0 requires all paths and bytes to match. Run the same command with native
zic 2022g as the failure control: it returns 1 and records 202 mismatches.
This evidence does not clear the archive or the ambiguous parent declaration;
the full inventory still has 159 held components.

## SBOM archive projection

The binder previously discarded `bundled_archives` despite their presence in
inventory. Each payload now has a CycloneDX file component with SHA-256, parent
artifact digest, path, size and explicit unresolved license scope. Each matching
parent component has an edge to this one file identity. No package URL or license
is inferred. Invalid paths, hashes, sizes, missing parent references and duplicate
payload identities fail closed.

The three affected test files pass 187 tests. Rebinding the retained exact-source
full inventory and scanner SBOM produces 616 components, including one explicit
`dateutil/zoneinfo/dateutil-zoneinfo.tar.gz` file and its parent edges. This is
projection proof using the recorded inventory revision, not a newly scanned
release or complete license adjudication. The 159 holds remain.

## Optimized Python validation

The standalone reproduction verifier initially used `assert` for pinned wheel,
source, archive path, entry and input-group validation. Python `-O` removes
those checks. A modified wheel with the same embedded payload but different ZIP
comment was accepted under `-O`, despite its different wheel digest.

All verifier input checks now raise ValueError explicitly. The optimized
wrong-wheel control is rejected before reading source or writing a receipt.
A runnable regression covers that boundary. With `python -O`, the real pinned
inputs still reproduce 598/598 timezone paths with exit 0, while native zic
2022g still matches only 396/598 and returns 1. Historical receipts retain their
original verifier hash; this change does not rewrite evidence history or clear
any licensing hold.
