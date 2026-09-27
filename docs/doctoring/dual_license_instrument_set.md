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

## Pip requirements parser: separately licensed vendored code

Do not register the root MIT grant/documentation set for
pip-requirements-parser 32.0.1. Its actual wheel also ships
`packaging_legacy_version.py`, whose complete header identifies a subset of
packaging.version 21.3 under BSD-2-Clause or Apache-2.0 and references a
separate license file. No such file is in the retained wheel. The complete
member inventory, wheel/source digests and header are recorded in
`evidence/release/1083/pip_requirements_vendored_license_gap.json`.
A root MIT declaration cannot cover this independently licensed component.

Upstream HEAD 4d18bc186553ca6ce619049dfdd63d4100f504a3 contains the three
vendored grant/wrapper files under src, but setup.cfg's explicit license_files
omits them. A one-line glob includes those existing files; the patch and
local build receipt are retained alongside the gap record. An unmodified
actual local wheel omitted all three, then the repaired actual wheel included
all three with byte-identical source contents; the vendored code is unchanged.
Build tools were installed only into the upstream checkout's isolated .venv,
from a pinned hash-locked tool manifest. Builds completed with exit 0.

The shallow-clone SCM warning and pre-existing MANIFEST missing-file warnings
were not suppressed. SCM emitted development versions, including its ordinary
dirty-build date suffix after the patch; these wheels are packaging probes,
not released 32.0.1 artifacts or reproducibility proof. No upstream PR or
publication occurred. The retained inventory remains 370 permitted, zero
copyleft, 143 held until the actual dependency artifact and separate scope
are verified. Future classification must retain the vendored grant choice
and component attribution instead of assigning MIT to all wheel contents.

## Hypothesis: root MPL does not close bundled scope

Hypothesis 6.165.10's root license explicitly excludes code noted otherwise
and identifies original project licenses as independently applicable. Its
actual wheel contains `hypothesis/vendor/pretty.py` with separate Ronacher /
Kern copyright and a BSD license designation. The only packaged license-like
file contains the root MPL instrument; it does not contain a full BSD grant.
Do not register the entire root text as authorizing every wheel component.

`evidence/release/1083/hypothesis_vendored_scope_gap.json` binds the actual
wheel, root instrument and component-source hashes, exact line excerpts and
scope limits. A lexical scan of Python source members locates additional
CPython copied/adapted-code comments. These are provenance leads requiring
verification, not established attribution or grant conclusions. Generated
output's CC0 designation likewise does not relicense its generator.

Next: trace the exact vendored source origin and its actual grant, preserve
component attribution and any separately applicable distribution terms, then
verify the actual artifact's complete evidence. No root matcher change or
license waiver is introduced. The full inventory remains 370 permitted,
zero copyleft, 143 held; artifact release is still unverified.

### Pretty printer source trace

The retained wheel member equals the source at Hypothesis `v6.165.10`, commit
6384deef469a88c147dab205f093b2d16d652785, byte for byte. The current path is
`hypothesis/src/hypothesis/vendor/pretty.py`; checking only the former
`hypothesis-python/src` path misses current source. Historical rename
ff5de7032db0ff7dd9632ace489dc2da597e3870 leads back to the original root-src
path. Initial vendoring commit 7f4dd55ff01cbd5e9aa24a500f10dfc8eda91b0f
explicitly says the printer is based on IPython with light changes.

The exact IPython origin revision is not stated there. Contemporaneous
IPython 4.1.2 resolves to b5734353b6d697be2bc4bc98333b0d29462533f9 and
contains full BSD-3-Clause terms, but this is a candidate, not proved copied
source. Its source/grant hashes and this limitation are recorded in the same
receipt. No candidate license was inserted or used to clear the artifact.

Primary history:
https://github.com/HypothesisWorks/hypothesis/commit/7f4dd55ff01cbd5e9aa24a500f10dfc8eda91b0f
https://github.com/HypothesisWorks/hypothesis/blob/6384deef469a88c147dab205f093b2d16d652785/hypothesis/src/hypothesis/vendor/pretty.py
https://github.com/ipython/ipython/blob/b5734353b6d697be2bc4bc98333b0d29462533f9/COPYING.rst

## Oxc platform package producer packaging

The retained @oxc-parser and @oxlint platform archives have no license
instruments. All 39 cached archives were rechecked against their lock-bound
SHA-512 integrity and exact package metadata. The current Oxc producer
8d8c1fc288cdc67482297077adff1c1a6ef44fb3 uses NAPI CLI 3.10.5 to create the
platform directories. That exact registry CLI archive was integrity verified
(SHA-256 fec42207108677024cbde344ee8018a3f54d0574912d79f9aee68ee827492e5e).
Its generator writes package metadata and README but no license instrument.
Oxc's prepublish checker verifies listed files, not missing license texts.

A local producer patch copies Oxc's existing LICENSE and THIRD-PARTY-LICENSE
before prepublish checks on all three native publish preparation paths:
reusable NAPI releases, oxlint, and oxfmt. The latter is a sibling path, not an
additional retained dependency. Use LICENSE.third-party for the second file:
actual npm pack excluded the first tried LICENSE-THIRD-PARTY filename under
the platform files allowlist. No provenance, publication or security step is
removed. Missing npm_dir or source instrument stops the isolated Bash step.

Actual offline metadata-only npm packs of all 39 retained package manifests
include both byte-identical producer instruments after running the exact YAML
copy snippet. Two representative RED packs omitted them before repair. These
probes omit native binaries and are not rebuilt or published native artifacts.
The receipt preserves the old archive identities separately from probe hashes;
no original registry tarball or inventory classification was changed.
Compiled Rust/native dependency scope and source provenance remain unresolved.
A future publication must verify those obligations, not apply root MIT to all
linked components.

The isolated shell passes shellcheck. Full actionlint exits 1 on both original
HEAD and repaired workflows, with the same 47 kind/message diagnostics:
existing local-action metadata and shell quoting errors remain. No whole-lint
pass is claimed. CodeGraph indexed the source with one known directory-symlink
fixture read error; no fixture was changed or deleted. The upstream patch has
not been committed, published or submitted as a PR. Any submission must follow
Oxc's AI-disclosure and contributor-review policy. Counts remain 370 permitted,
zero copyleft, 143 held. Patch and packaging receipts are retained under
`evidence/release/1083/oxc_platform_license_packaging.*`.

## Hosted quality execution after runner repairs

Security run 36330029062 at predecessor main
7116592c7599cd8cb45ba9bf31b89be6d4f0fd3f completed the Tests and package
quality job 108650067894 successfully, including Compose verification, native
measurement build, full tests, benchmark coverage and installed-wheel checks.
The full suite recorded 5300 passed, five native-tokenizer skips and two
unsuppressed deprecation warnings. Benchmark proof recorded 190 passed and
100% branch coverage for nim_benchmark.py; installed-wheel checks recorded
40 passed. This is not strict-warning or native-tokenizer acceptance.

The separate predecessor Rust job failed linking libpython; repair #1311 is
merged at b08d0105269ef7cf3919836ab92aa12b6b5d6f14. Its four exact-main
Security jobs remain queued at this observation. All six organization runners
are online and busy; the three execution groups already admit this Security
workflow. Reassigning labels adds no available execution capacity. Preserve
the control group reservation. Latest-main terminal gates and immutable
release evidence remain separate. Receipt:
`evidence/release/1083/hosted_quality_predecessor.json`.

## License-expression bundled scope

The retained license_expression-30.4.4 wheel (SHA-256
421788fdcadb41f049d2dc934ce666626265aeccefddd25e162a26f23bcbf8a4)
contains the complete Apache grant and five additional documentation/notice
instruments. All six were checked against the actual archive, read completely,
and retained by hash. README GPL expressions are parser examples, not grants.

The wheel also ships _pyahocorasick.py with an explicit
LicenseRef-scancode-public-domain declaration, author attribution and
modification description. Its bytes and the bundled ScanCode index match tag
v30.4.4 commit a3c00c09986bcca1240afd5b1844b56de3f581c1 exactly. This proves
producer-source correspondence, not the original copied revision or complete
redistribution scope. Catalog license keys/categories describe indexed
licenses; they do not license the catalog data itself. The bundled Contributor
Covenant adaptation also needs its scope accounted for. No complete-set
registration or whole-wheel Apache clearance was made. Counts remain
370 permitted, zero copyleft, 143 held. The source-bound receipt is
`evidence/release/1083/license_expression_vendored_scope.json`.

### Exact original pure-Python revision recovered

Initial import 025fee38d84aa19f32050c0802eb27e0f0852bc7 (2017-01-11)
added _pyahocorasick.ABOUT with an explicit original revision:
ec2fb9cb393f571fd4316ea98ed7b65992f16127, path py/pyahocorasick.py.
This resolves the prior missing-original-revision finding. The original
file declares public domain while the same repository revision has a complete
three-clause BSD root LICENSE. Preserve this file-versus-root scope distinction;
neither declaration is silently substituted for the other. The importer changed
spacing, blank lines and one demo variable name, so byte identity is false.
The full diff and hashes are retained in
`evidence/release/1083/license_expression_original_code_provenance.json`.
Later modification grants, bundled data and documentation scope remain to be
resolved. No license was transplanted and no classification was changed.

## Package-body instrument collection repair

The actual license-expression wheel includes cc-by-4.0.LICENSE and both
ABOUT records outside dist-info. Previous inventory evidence omitted these
files because collection was restricted to distribution metadata directories.
The bundled index is byte-identical to ScanCode LicenseDB revision
1dfa89ae348338b23a359c4c6b23e39c128a41e5 docs/index.json; its bundled ABOUT
explicitly declares cc-by-4.0. The provenance and instrument exist in the wheel,
so this is a collector gap, not a missing upstream packaging instrument.

The collector now retains bounded package-body license/notice/ABOUT candidates
separately, excluding source/binary modules named license. Root declarations
do not authorize these instruments: classification holds their unresolved
package-body scope. Actual archive probes recover license-expression, numpy
and pip evidence; existing distribution metadata ownership checks remain.
The retained full inventory still classifies 370 permitted, zero copyleft and
143 held. A regression fails before repair and the affected suites pass 256
tests afterward. This does not cover every arbitrary instrument filename or
source-header grant. Receipt:
`evidence/release/1083/package_body_license_collection.json`.

### Shared Cargo/npm instrument selection

The native archive selector had the same suffix omission as the wheel path,
and incorrectly treated source modules named license.js/license.rs as license
instruments. Wheel package-body and Cargo/npm collection now reuse one candidate
selector: known instrument prefixes and .LICENSE/.LICENCE/.ABOUT suffixes,
excluding common source/binary module extensions. Explicit Cargo license-file
paths remain authoritative and keep their independent bounded read validation.
No identity, digest, archive path, link, size or registry-origin gate changed.

Both Cargo/npm regression cases fail before repair and the affected suites
pass 258 tests afterward. A fresh offline scan verified 388 cached registry
archives against their lock digests and recovered seven suffix instruments
from lz-string, playwright and playwright-core. No old evidence files were
removed in that actual scan. No registry download or package hook was executed.
The retained full inventory remains 370 permitted, zero copyleft and 143 held;
this is collection evidence, not complete bundled-code license clearance.
Receipt: `evidence/release/1083/native_instrument_selector.json`.

## Playwright inlined-component inventory gap

The recovered Playwright and Playwright-core bundle instruments name inlined
packages that are not represented by those root npm identities alone. Five
structured notice manifests contain 175 distinct name/version pairs; 132
are absent from the retained npm inventory. Each list matches its notice
section headings, end markers and stated package count exactly. Both original
registry archives were rechecked against their lock SHA-512 and the five
notice SHA-256 values. The producer manifests, missing identity list and
archive bindings are retained in
`evidence/release/1083/playwright_inlined_component_gap.json`.

These are producer-declared inlined identities, not independently verified
component archive hashes or complete binary composition. Existing lock
inventory is therefore not full bundle-composition proof. Do not fabricate
component digests, dependency edges or license clearance from root Apache.
The unstructured webp codec instrument is outside this five-manifest count
and still needs separate scope review. No SBOM component or classifier waiver
was added; the previous 370/0/143 classification is unchanged and is not a
count of these newly identified inlined components. Next: establish grants
and provenance for these explicit included components before release proof.

## Requests-toolbelt producer instrument repair

The locked requests_toolbelt 1.0.0 wheel includes AUTHORS and only the Apache
application notice, not the full conditions. Exact tag 1.0.0 commit
b7d1a1fcdda9ebcd9afe5011690ab860fce780c2 and current upstream
bcd5f7be229e14089052be7e3b527ebcea0ae7b8 have the same short LICENSE notice.
A minimal local patch appends the byte-verified complete official Apache text
to that existing file, preserving the original notice and AUTHORS. Existing
packaging includes it; no configuration or classifier change is required.

Actual RED/GREEN wheel builds use the existing isolated, hash-locked tools
(setuptools80.9.0/wheel0.45.1/packaging26.2). GREEN includes the exact repaired
LICENSE and AUTHORS; all 33 Python files are byte-identical before/after patch.
The locked registry wheel has an extra adapters/appengine.py absent from the
exact tag. The other 33 Python files match. An initial whole-code match check
failed on this discrepancy, so complete registry source provenance is not
claimed. No registry archive was rewritten or reclassified.

Builds finish exit0 with unsuppressed legacy packaging/classifier/universal
wheel deprecations, MANIFEST notices and cookies package configuration warning.
This is packaging proof, not full runtime, reproducibility or release approval.
The one-file upstream patch remains local and unpublished. Receipt and patch:
`evidence/release/1083/toolbelt_license_packaging.*`. Current gate totals remain
384 permitted, one GPL-declaration blocker, 144 held for the 529-entry scope.
