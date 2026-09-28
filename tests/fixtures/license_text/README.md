# Complete license instrument regression fixtures

Canonical source: SPDX license-list-data commit
`31ba1a50e5397e00a304dbadc76531740e89ee48`, resolved from its public Git HEAD
on 2026-09-27. These fixtures are complete license texts, not package metadata
or excerpts. The LLVM fixture concatenates the Apache-2.0 text and LLVM
exception text. The collector's target-lexicon archive uses three rather than
four leading title dashes; both complete forms are pinned separately.

| Source JSON under that commit | Raw JSON SHA256 |
| --- | --- |
| `json/details/Apache-2.0.json` | `b0f85bc041014e63212f71924bf154e0fae058c03356b3185b092028a74811b4` |
| `json/exceptions/LLVM-exception.json` | `caad73fc83226f9762861f2447e9f8b8cdfa46907f6f95ee79e064185dec7c6a` |
| `json/details/MPL-2.0.json` | `b909c2b38d4ab47ab70dd45327bb6e547a4dc8fd2ea4877ca083f12effbe294f` |
| `json/details/BlueOak-1.0.0.json` | `3cc2f71df061d15d713f96dc38a9eb82c13af76d8455a6ed483a5597dd1aeade` |

Only whitespace is normalized by the production matcher. An altered,
truncated, prefixed or extended instrument does not obtain a canonical match.
Any unmatched second file, including unknown conditions, holds the package.
Mixed legacy declarations keep the prior conservative path. Known canonical declarations
cannot fall back to the old title/keyword matcher. No package/version or
filename allowlist is introduced, and there is no runtime reference download.
This implements the existing declaration policy; it does not waive license
obligations or authorize a release.

Primary definitions:
[SPDX LLVM exception](https://spdx.org/licenses/LLVM-exception.html),
[SPDX MPL-2.0](https://spdx.org/licenses/MPL-2.0.html),
[SPDX BlueOak-1.0.0](https://spdx.org/licenses/BlueOak-1.0.0.html).
Source bytes are independently retrievable from
[`spdx/license-list-data` at the recorded commit](https://github.com/spdx/license-list-data/tree/31ba1a50e5397e00a304dbadc76531740e89ee48).

## Repair evidence

At predecessor head `db1d1ea0`, all three canonical-instrument regressions
failed by classifying the complete standard texts as undecidable (3 failures,
process exit 1). The unchanged native archive inventory at `f55915af` can be
reclassified without refetching or changing any instrument: Cargo rises from
41 to 42 permitted entries out of 43; npm rises from 212 to 227 out of 359.
The remaining 133 native holds are retained. In particular, missing instruments,
modified/prefixed license texts and unreviewed formatting variants are not
invented into permission. Python wheels and full release/SBOM evidence remain
separate unfinished work.

Verification: the final focused inventory/classifier/workflow/install-gate command
passed 194 tests with process exit 0; the minimal-interpreter config warning was
retained. `git diff --check` passed. These are local receipts, not hosted or
release acceptance.
