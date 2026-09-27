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
identity and instrument, not the transformation into every embedded TZif byte.
[IANA database and release documentation](https://data.iana.org/time-zones/tz-link.html).

## Acceptance gap

The source-to-embedded transformation, per-member ownership, instrument
projection and complete SBOM child scope remain unverified. The payload remains
held. Archive-suffix detection is not a universal binary format detector; a
complete release must also account for hidden formats, vendor code, toolchain
and container layers. No parent license, filename, development scope or publisher
waiver is added. Full release and downstream acceptance remain incomplete.

```sh
uv run --locked --extra test python -m pytest -q tests/test_dependency_inventory.py \
  -k 'bundled_archive_has or nested_archive_size'
```
