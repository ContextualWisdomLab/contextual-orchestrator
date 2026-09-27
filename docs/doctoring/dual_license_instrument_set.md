# Complete dual-license instrument set

The exact aho-corasick 1.1.5 and memchr 2.8.3 archives contain the same complete
MIT grant, Unlicense grant and a separate selection notice. The notice says:

> This project is dual-licensed under the Unlicense and MIT licenses.
> You may use this code under the terms of either license.

The notice grants no independent permission. The previous matcher rejected it
because it is not itself a full instrument. The repair requires all three
complete whitespace-normalized text hashes for the exact declaration
`Unlicense OR MIT`. Missing, duplicate, altered or additional texts fail closed.
Package names and filenames do not participate in the decision. The full texts
are retained as test fixtures; each grant was read in full, including warranty
and attribution clauses.

Verified archive sources and SHA-256:

- https://static.crates.io/crates/aho-corasick/aho-corasick-1.1.5.crate
  `c982642fa9e8606056828ee9a8505737230110bb1099153c79efe865c59d12ba`
- https://static.crates.io/crates/memchr/memchr-2.8.3.crate
  `cf8baf1c55e62ffcace7a9f06f4bd9cd3f0c4beb022d3b367256b91b87513d98`

This deliberately supports only complete reviewed text sets. Other copyright
variants need separate complete evidence; no general notice parser is added.

The new positive control fails before the repair. Notice-only, missing each
instrument, changed notice and additional GPL controls remain rejected. The
three affected test files pass 193 tests (exit 0). Reclassifying the retained
full inventory yields 356 permitted, zero copyleft and 157 held entries. Only
these two Cargo holds change. This is artifact license evidence, not protected
main delivery, a released SBOM, full toolchain/container scope or downstream
runtime acceptance.

## Apache/BSD sets

The same three-instrument check now recognizes the complete reviewed
Apache-2.0/BSD-3-Clause set and Apache-2.0/BSD-2-Clause set. All clauses were
read, including patent termination, attribution, redistribution, contribution
and warranty terms. Exact selection notices and both complete grants are
required. No generic notice parser or file exemption is introduced.

The matching source wheel and raw text digests are recorded in
`evidence/release/1083/apache_bsd_instrument_sources.json`; complete texts are
fixtures. The declaration is still checked separately and missing, changed or
additional instruments remain blocked. Packaging 26.2 and 26.3 have identical
instrument sets but distinct wheel digests.

The prior-head matcher rejects both positive sets; the repaired matcher accepts
them. All 203 affected tests pass. Reclassification changes exactly cryptography
50.0.1 and packaging 26.2/26.3: holds 157 to 154, with no other change. This is
license-text adjudication, not an audit of embedded native library provenance.

## Complete BlueOak Markdown rendering

minimatch 10.2.6 carries the full BlueOak-1.0.0 instrument with `**_…_**`
emphasis in place of `***…***`, plus whitespace changes. The entire text was
read and compared with the pinned SPDX fixture: after replacing only those two
specific emphasis markers in the comparison, all normalized text is identical.
Production adds only the complete rendering's SHA-256, not a Markdown parser
or partial-text rule. The extra fixture and mutation rejection make this
comparison repeatable. An altered clause or additional file remains held.

Source: https://registry.npmjs.org/minimatch/-/minimatch-10.2.6.tgz

Locked archive SHA-512:
`be92d012cf952c2af59d4d015d2d3b99a628170943007d209e042ebadb71230bad0c510c1ead9b957fbcbe98310dd2b72753f08c22627a9efb3a2b536782e5d4`

Complete whitespace-normalized text SHA-256:
`d1d8b7a22428eba7e46e7e373d014141266ead51a00c9291a4792278110a8997`

204 affected tests pass (exit 0). The retained inventory changes exactly this
one npm hold, leaving 153 held entries. Of the remaining npm holds, 128 have no
license text in their exact archives and seven need further instrument/scope
evidence. Glob's instrument explicitly excludes its `src/` scope; it remains
held. No platform package inherits its parent's permission.

## Explicit complete MIT/Apache metadata set

sniffio 1.3.1 declares `MIT OR Apache-2.0`, `MIT License` and
`Apache Software License`, and contains a selection notice plus complete MIT
and Apache grants. The notice and MIT grant were read in full; comparison of
the complete Apache grant with the previously reviewed instrument differs only
in the two HTTP/HTTPS links. Exact full hashes are pinned independently.

The reviewed set recognizes exactly these three metadata terms and all three
complete instruments. It does not coerce unknown aliases or permit an
unrecognized notice. Missing either grant, notice-only, additional GPL or an
altered notice remains rejected. The wheel SHA-256 is
`2f6da418d1f1e0fddd844478f41680e794e6051915791a034ff65e5f100525a2`.
Complete texts are retained as `sniffio-instrument-*.txt` fixtures.

The prior matcher rejects this real complete set. All 211 affected tests pass;
actual inventory changes exactly sniffio 1.3.1: 361 permitted, zero copyleft,
152 held. Linux installed-pair execution is still separate and pending.

## Complete Apache grant and attribution

CycloneDX Python Lib 11.11.0 carries the complete Apache grant, identical after
whitespace normalization to the previously reviewed Apache fixture, plus a
NOTICE containing only copyright and community attribution. Exact artifact and
text digests are recorded in `evidence/release/1083/apache_attribution_set.json`;
the NOTICE is retained as a fixture. Both full hashes and exactly two files
are required for this additional path. An altered grant, altered attribution,
notice-only, extra terms or duplicate file is rejected. Existing single-grant
archives keep their prior path; no generic notice exemption is added.

The original matcher rejected the actual complete pair. Full retained inventory
comparison changes exactly CycloneDX: 362 permitted, zero copyleft, 151 held.
All 207 affected tests pass with process exit 0.
Requests remains held: its license file omits the Apache appendix and end marker,
so it is not this complete instrument. This evidence does not waive retained
notices, establish native/container provenance or authorize release.

## Complete CC-BY-4.0 instrument

caniuse-lite 1.0.30001810 carries the complete Attribution 4.0 International
text. Its declared identifier was already recognized, but the legacy matcher
had no text-evidence branch for this family. The complete instrument was read
and compared with the official Creative Commons plain text, including
attribution, database rights, termination and surviving conditions. After
whitespace normalization, the only difference is `More_considerations` versus
`More considerations` in the introductory informational paragraph.

Both complete-text hashes are pinned; no punctuation/word normalizer or
filename exemption is added. The fixture retains the exact archive text and
a regression reconstructs the official normalized digest with only that
explicit introductory substitution. Existing mutation, truncation, additional
unknown/GPL file and wrong-declaration controls also cover this instrument.
Artifact identity, full source/text digests and the retained inventory's
original source identity are in `evidence/release/1083/cc_by_instrument.json`.

The real complete-text positive control failed before the repair. All 214
affected tests pass with process exit 0. Reclassification changes exactly
caniuse-lite: 363 permitted, zero copyleft, 150 held. Attribution and notice
obligations remain; this is not release or container/native provenance approval.

Primary source: https://creativecommons.org/licenses/by/4.0/legalcode.txt

## Complete historical Python license instrument

typing-extensions 4.15.0 and 4.16.0 each carry one pure Python module and one
license instrument. Both entire texts match CPython 3.12.0's LICENSE after
whitespace normalization. The annotated tag was peeled to immutable source
commit `0fb18b02c8ad56299d6a2910be0bab8ad601ef24`; fetching LICENSE at that commit
confirmed the versioned-tag bytes. The complete text was read, including
historical PSF, BeOpen, CNRI, CWI and documentation grants. The prior keyword
matcher rejected historical GPL-compatibility mentions rather than a GPL grant.

Reuse the complete-instrument path for the exact `PSF-2.0` declaration and
full-text digest, preserving the entire fixture and all historical conditions.
An altered or truncated instrument, an extra unknown/GPL file and a GPL
declaration still fail. No short family-name or GPL-mention exception is added.
The record `evidence/release/1083/psf_instrument.json` binds both exact wheel
digests, archive contents, full primary-source digest and original inventory
source SHA. This does not classify CPython's separate embedded libraries.

The real positive control failed before repair. All 220 affected tests pass
with process exit 0. Reclassification changes exactly the two typing-extensions
identities: 365 permitted, zero copyleft, 148 held. Release and full native/
container/toolchain provenance remain separate.

Primary source:
https://raw.githubusercontent.com/python/cpython/0fb18b02c8ad56299d6a2910be0bab8ad601ef24/LICENSE

## Complete MIT grant and authors attribution

pytest-cov 7.1.0 carries the full MIT grant and a separate AUTHORS list. Both
were read in full; the author list contains attribution, not an additional
grant or restriction. The artifact declares exactly `MIT` and `MIT License`.
Reuse the existing exact complete-grant/attribution path for these terms and
the two entire normalized hashes. The exact wheel and both raw files were
rechecked against `evidence/release/1083/mit_attribution_set.json`.

No AUTHORS filename exemption is introduced. Notice-only, changed grant or
author list, additional GPL text and duplicate files remain rejected. The
parameterized controls cover both Apache and MIT pairs, and the existing
single-grant path remains intact. Both complete files are retained as fixtures.

The real complete pair failed before repair. All 227 affected tests pass,
process exit 0. Full retained inventory comparison changes only pytest-cov:
366 permitted, zero copyleft, 147 held. Copyright/attribution obligations and
all separate native/container/provenance/release requirements remain.

## Complete BSD grant and Pygments attribution

Pygments 2.20.0 and 2.21.0 include the complete BSD-2-Clause grant and its
explicitly referenced AUTHORS list. Both lists were read in full; the version
change adds four contributor rows and no additional grant or restriction.
The actual retained wheel and every raw license file digest were verified.
`evidence/release/1083/bsd_attribution_set.json` preserves those identities and
the original inventory source SHA. Both complete versions remain fixtures.

Reuse the exact complete-grant/attribution path with two separately reviewed
full hash sets. This introduces no filename exemption. Changed grant,
changed attribution, notice-only, duplicate and additional GPL text remain
rejected; existing single-instrument grants retain their original path.
The real two complete pairs failed before repair. The license-gate suite
passes 153 tests with process exit 0. Full inventory comparison changes only
these two Pygments identities: 368 permitted, zero copyleft, 145 held.
Distribution attribution obligations and separate release requirements remain.

## Requests full Apache terms and NOTICE

Requests 2.34.2 contains all Apache-2.0 terms, sections 1–9, plus its
copyright NOTICE. Its LICENSE omits the end marker and application appendix.
Every normalized word before the official ASF end marker matches the
retained wheel LICENSE; no substantive term is missing or changed. The
ASF definition identifies sections 1–9 as the license, while its application
page describes the appendix as instructions for applying the license.
This is a source comparison, not a general permission to truncate licenses.

Primary sources:
https://www.apache.org/licenses/LICENSE-2.0.txt
https://www.apache.org/legal/apply-license.html

The actual wheel and both raw files were reverified. Their identities and
the primary-source hash are in `evidence/release/1083/requests_apache_terms.json`.
Reuse the existing exact full-grant/attribution matcher for this complete
pair. Missing section, modified grant, changed NOTICE, extra GPL text,
notice-only, duplicate and wrong declaration controls remain rejected.
The existing legacy single-grant path already accepted this LICENSE alone;
that behavior is preserved, not introduced by the new pair registration.
Neither the fixture nor the registration removes redistribution obligations.

The real complete pair failed before repair. Full retained inventory changes
only requests: 369 permitted, zero copyleft, 144 held. Native/container,
provenance, hosted CI and release clearance remain separate.

## Boolean.py full grant and packaged documentation

boolean.py 5.0 carries a complete BSD-2-Clause grant, a README with the same
copyright/SPDX designation, and a release/API CHANGELOG. All three documents
were read in full; neither auxiliary document adds a grant or restriction.
The exact retained wheel and all three raw files were reverified, and the
complete files remain fixtures. Their original-source identities are recorded
in `evidence/release/1083/boolean_py_instrument_set.json`.

Reuse the existing exact complete-grant/attribution set matcher for these
three complete normalized hashes and the sole BSD-2-Clause declaration.
There is no README/CHANGELOG filename exemption. Missing or changed grant,
changed README or changelog, additional GPL text, duplicates and wrong
license declarations remain rejected. Distribution obligations remain.
The real complete set failed before repair. Full inventory comparison changes
only boolean.py 5.0: 370 permitted, zero copyleft, 143 held. Remaining
native/container/provenance/CI/release requirements are not cleared.
