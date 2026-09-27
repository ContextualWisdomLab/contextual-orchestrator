# UNLICENSE artifact evidence (2026-09-27)

The #1302 release stack omitted legacy wheel, installed-distribution and
native-archive files named UNLICENSE from license evidence. The same prefix
list also excluded UNLICENSE from orphan-wheel ownership checks. Naming a
file does not establish its license; omitting it can conceal extra terms.

The existing four selectors now also collect UNLICENSE-prefixed files.
Archive identity/digests, bounded reads, link refusal, ownership checks and
license classification are unchanged. No archive extraction or hooks run.

Three RED controls (Cargo/npm/wheel with MIT metadata and a GPL-bearing
UNLICENSE sibling) failed before the fix. Afterward, 164 inventory/license/
SBOM tests pass (exit 0). Installed LICENSE/UNLICENSE byte and outside-symlink
controls additionally pass all four cases. These controls refuse permission
when the newly collected file contains GPL, regardless of its filename.

Actual locked aho-corasick 1.1.5 archive SHA-256
c982642fa9e8606056828ee9a8505737230110bb1099153c79efe865c59d12ba
contains COPYING, LICENSE-MIT and UNLICENSE; the earlier inventory recorded
only the first two. The new evidence must record all three. Its existing
conservative hold for the COPYING notice is not waived by this repair.

This closes a collector gap, not final license, provenance or release
acceptance. Remaining missing instruments and unresolved supporting documents
remain held. Regression command:

```sh
uv run --locked --extra test python -m pytest -q tests/test_dependency_inventory.py \
  -k 'unlicense_named_file or installed_license_bytes'
```
